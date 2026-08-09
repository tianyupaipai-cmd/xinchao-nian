"""Privacy-preserving admission gate for *automatic* memory writes.

Manual MCP calls are intentionally outside this gate.  A first-time sentence
explicitly chosen by the user or the companion must never depend on repetition
or a model-computed weight.

Automatic candidates are conservative:

* technical-only material is rejected;
* explicit high-impact signals may pass on their first occurrence;
* ordinary candidates need one exact repeat;
* the candidate ledger stores hashes and decisions, never candidate text.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Optional


_TECH_PATTERNS = (
    re.compile(r"\b(?:api|mcp|oauth|docker|nginx|systemd|github|git|vps|ssh|dns|"
               r"token|cookie|database|sqlite|python|node(?:\.js)?|cloudflare)\b", re.I),
    re.compile(r"(?:端口|容器|镜像|部署|服务器|数据库|接口|密钥|配置文件|技术文档|代码|函数|分支|提交)"),
    re.compile(r"(?:https?://|/[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+|\b\d{1,3}(?:\.\d{1,3}){3}\b)"),
)

_PERSONAL_PATTERNS = (
    re.compile(r"(?:喜欢|讨厌|害怕|难过|开心|委屈|心疼|想念|信任|在意|感动|爱|关系)"),
    re.compile(r"(?:承诺|约定|边界|习惯|偏好|陪伴|照顾|抱住|记着|别忘|不要忘)"),
    re.compile(r"(?:顾川|小雨|派派|朱天雨)"),
)

_FIRST_PASS_PATTERNS = (
    re.compile(r"(?:承诺|约定|边界|以后记得|帮你记|我会记|不要忘|不能忘)"),
    re.compile(r"[“「][^”」]{2,160}[”」]"),
)


@dataclass(frozen=True)
class WriteAdmission:
    allowed: bool
    decision: str
    reason: str
    candidate_id: str = ""
    prior_count: int = 0


def decide_write(
    content: str,
    *,
    auto: bool = False,
    source: str = "",
    importance: int = 5,
    pinned: bool = False,
    why_remembered: str = "",
    meaning: str = "",
    ledger_path: Optional[Path] = None,
) -> WriteAdmission:
    text = " ".join(str(content or "").split()).strip()
    if not text:
        return WriteAdmission(False, "skip", "empty")

    # The non-negotiable escape hatch: explicit/manual writes never enter the
    # candidate ledger and never wait for repetition.
    if not auto:
        return WriteAdmission(True, "manual_direct", "manual_bypass")

    candidate_id = hashlib.sha256(
        (str(source or "auto").strip().lower() + "\0" + text).encode("utf-8")
    ).hexdigest()[:20]

    technical_score = sum(1 for pattern in _TECH_PATTERNS if pattern.search(text))
    personal_score = sum(1 for pattern in _PERSONAL_PATTERNS if pattern.search(text))
    if technical_score >= 1 and personal_score == 0:
        decision = WriteAdmission(
            False,
            "skip",
            "technical_only",
            candidate_id=candidate_id,
        )
        _record(ledger_path, decision, source)
        return decision

    explicit_weight = (
        bool(pinned)
        or int(importance or 5) >= 7
        or bool(str(why_remembered or "").strip())
        or bool(str(meaning or "").strip())
        or any(pattern.search(text) for pattern in _FIRST_PASS_PATTERNS)
    )
    if explicit_weight:
        decision = WriteAdmission(
            True,
            "grow",
            "first_occurrence_high_impact",
            candidate_id=candidate_id,
        )
        _record(ledger_path, decision, source)
        return decision

    prior_count = _prior_count(ledger_path, candidate_id)
    if prior_count >= 1:
        decision = WriteAdmission(
            True,
            "grow",
            "exact_repeat",
            candidate_id=candidate_id,
            prior_count=prior_count,
        )
        _record(ledger_path, decision, source)
        return decision

    decision = WriteAdmission(
        False,
        "pending",
        "automatic_candidate_needs_review_or_repeat",
        candidate_id=candidate_id,
    )
    _record(ledger_path, decision, source)
    return decision


def default_ledger_path(config: dict) -> Path:
    buckets_dir = Path(str(config.get("buckets_dir") or "buckets"))
    return buckets_dir / ".companion" / "auto-write-candidates.jsonl"


def _prior_count(path: Optional[Path], candidate_id: str) -> int:
    if path is None or not path.exists():
        return 0
    count = 0
    try:
        for line in path.read_text(encoding="utf-8").splitlines()[-500:]:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if item.get("candidate_id") == candidate_id:
                count += 1
    except OSError:
        return 0
    return count


def _record(path: Optional[Path], decision: WriteAdmission, source: str) -> None:
    if path is None:
        return
    record = {
        "candidate_id": decision.candidate_id,
        "source": str(source or "auto")[:80],
        "decision": decision.decision,
        "reason": decision.reason,
        "prior_count": decision.prior_count,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        # Admission must fail closed for pending candidates, but an already
        # admitted high-impact write must not be lost merely because its
        # metadata-only audit could not be appended.
        return
