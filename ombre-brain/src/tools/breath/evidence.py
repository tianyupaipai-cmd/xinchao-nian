"""Conservative direct-evidence gate for query-driven memory recall.

Ranking answers "which candidates are closest"; admission answers the stricter
question "is there enough evidence to show this bucket at all?"  Importance,
recency, emotion and activation frequency must never admit an otherwise
unrelated memory.

This module is deliberately local and deterministic.  It does not send memory
text to another model and it does not mutate any bucket.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Optional
import unicodedata


_ASCII_WORD = re.compile(r"[a-z0-9][a-z0-9._+-]{1,}")
_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_SPACE = re.compile(r"\s+")

_ASCII_STOP = {
    "about",
    "again",
    "before",
    "memory",
    "remember",
    "said",
    "that",
    "the",
    "this",
    "what",
    "when",
    "with",
    "you",
}

# These fragments are useful conversational glue but weak topic evidence.
_CJK_WEAK_GRAMS = {
    "什么",
    "之前",
    "刚才",
    "昨天",
    "记得",
    "我们",
    "你说",
    "我说",
    "那个",
    "这个",
    "时候",
    "事情",
}


@dataclass(frozen=True)
class Admission:
    allowed: bool
    reason: str
    lexical_support: int = 0
    semantic_score: float = 0.0


def admit_direct_memory(
    query: str,
    bucket: dict,
    *,
    semantic_score: Optional[float] = None,
    semantic_high: float = 0.84,
    semantic_supported: float = 0.72,
) -> Admission:
    """Return whether a bucket has enough direct evidence for ``query``.

    Rules are intentionally conservative:

    * an exact literal phrase is direct evidence;
    * strong lexical anchors plus a supported semantic score are evidence;
    * an exceptionally high semantic score can stand alone;
    * importance/recency/emotion are never evidence.
    """

    query_text = _normalise(query)
    haystack = _bucket_haystack(bucket)
    score = _safe_score(semantic_score)
    if not query_text or not haystack:
        return Admission(False, "empty", semantic_score=score)

    compact_query = _compact(query_text)
    compact_haystack = _compact(haystack)
    if len(compact_query) >= 2 and compact_query in compact_haystack:
        return Admission(True, "literal", lexical_support=3, semantic_score=score)

    ascii_overlap = _ascii_anchors(query_text) & _ascii_anchors(haystack)
    cjk_overlap = _cjk_anchors(query_text) & _cjk_anchors(haystack)
    lexical_support = min(3, len(ascii_overlap) + len(cjk_overlap))

    # Very short CJK queries are prone to accidental overlap.  They need a
    # literal match or unusually strong semantic agreement.
    cjk_len = len(_cjk_chars(query_text))
    if score >= semantic_high:
        return Admission(
            True,
            "semantic_high",
            lexical_support=lexical_support,
            semantic_score=score,
        )
    if cjk_len and cjk_len <= 3:
        return Admission(
            False,
            "short_query_without_literal",
            lexical_support=lexical_support,
            semantic_score=score,
        )

    if lexical_support >= 1 and score >= semantic_supported:
        return Admission(
            True,
            "semantic_with_anchor",
            lexical_support=lexical_support,
            semantic_score=score,
        )

    # Multiple independent lexical anchors are sufficient even when the
    # semantic provider is unavailable.
    if lexical_support >= 2:
        return Admission(
            True,
            "lexical_anchors",
            lexical_support=lexical_support,
            semantic_score=score,
        )

    return Admission(
        False,
        "insufficient_direct_evidence",
        lexical_support=lexical_support,
        semantic_score=score,
    )


def _bucket_haystack(bucket: dict) -> str:
    meta = bucket.get("metadata", {}) or {}
    fields = [
        str(meta.get("name") or ""),
        " ".join(str(item) for item in (meta.get("tags") or [])),
        " ".join(str(item) for item in (meta.get("domain") or [])),
        str(bucket.get("content") or ""),
    ]
    return _normalise(" ".join(fields))


def _normalise(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    return _SPACE.sub(" ", text).strip()


def _compact(value: str) -> str:
    return "".join(ch for ch in value if ch.isalnum() or _CJK.fullmatch(ch))


def _ascii_anchors(value: str) -> set[str]:
    return {
        word
        for word in _ASCII_WORD.findall(value)
        if len(word) >= 3 and word not in _ASCII_STOP
    }


def _cjk_chars(value: str) -> str:
    return "".join(_CJK.findall(value))


def _cjk_anchors(value: str) -> set[str]:
    chars = _cjk_chars(value)
    if len(chars) < 3:
        return set()
    grams: set[str] = set()
    for size in (2, 3, 4):
        for index in range(0, len(chars) - size + 1):
            gram = chars[index : index + size]
            if any(weak in gram for weak in _CJK_WEAK_GRAMS):
                continue
            grams.add(gram)
    return grams


def _safe_score(value: Optional[float]) -> float:
    try:
        score = float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, score))
