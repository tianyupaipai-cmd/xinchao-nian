from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterator


LEDGER_SCHEMA_VERSION = 1
LEDGER_ROLE = "mirror"


class LedgerMirror:
    """Append-only JSONL mirror for successful memory mutations.

    Phase 1 mirror only: this is an audit/replay seed beside Markdown, not the
    canonical source of truth yet.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def append_event(
        self,
        *,
        event_type: str,
        trace_id: str,
        trace_kind: str,
        payload: dict[str, Any] | None = None,
        body: str = "",
    ) -> dict[str, Any]:
        body_hash = _hash_body(body)
        event = {
            "seq": self.latest_seq() + 1,
            "schema_version": LEDGER_SCHEMA_VERSION,
            "ledger_role": LEDGER_ROLE,
            "canonical": False,
            "event_type": str(event_type),
            "trace_id": str(trace_id),
            "trace_kind": str(trace_kind),
            "body_hash": body_hash,
            "payload": _json_safe(payload or {}),
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_append_starts_on_new_line()
        with self.path.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(event, ensure_ascii=False, sort_keys=True))
            f.write("\n")
        return event

    def latest_seq(self) -> int:
        latest = 0
        for event in self.iter_events():
            try:
                latest = max(latest, int(event.get("seq", 0)))
            except (TypeError, ValueError):
                continue
        return latest

    def iter_events(self) -> Iterator[dict[str, Any]]:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue

    def verify_integrity(self) -> dict[str, Any]:
        valid_events = 0
        invalid_lines: list[int] = []
        latest_seq = 0
        schema_versions: set[int] = set()
        if not self.path.exists():
            return {
                "ok": True,
                "path": str(self.path),
                "ledger_role": LEDGER_ROLE,
                "canonical": False,
                "valid_events": 0,
                "invalid_lines": [],
                "latest_seq": 0,
                "schema_versions": [],
            }

        with self.path.open("r", encoding="utf-8") as f:
            for lineno, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    invalid_lines.append(lineno)
                    continue
                valid_events += 1
                try:
                    latest_seq = max(latest_seq, int(event.get("seq", 0)))
                except (TypeError, ValueError):
                    invalid_lines.append(lineno)
                try:
                    schema_versions.add(int(event.get("schema_version")))
                except (TypeError, ValueError):
                    invalid_lines.append(lineno)

        return {
            "ok": not invalid_lines,
            "path": str(self.path),
            "ledger_role": LEDGER_ROLE,
            "canonical": False,
            "valid_events": valid_events,
            "invalid_lines": invalid_lines,
            "latest_seq": latest_seq,
            "schema_versions": sorted(schema_versions),
        }

    def purge_trace(self, trace_id: str) -> int:
        """Remove every mirror event for one trace without reading memory bodies."""
        if not self.path.exists():
            return 0
        kept: list[str] = []
        removed = 0
        with self.path.open("r", encoding="utf-8") as source:
            for line in source:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    event = json.loads(stripped)
                except json.JSONDecodeError:
                    kept.append(stripped)
                    continue
                if str(event.get("trace_id") or "") == str(trace_id):
                    removed += 1
                else:
                    kept.append(json.dumps(event, ensure_ascii=False, sort_keys=True))
        if not removed:
            return 0
        temp_path = self.path.with_name(
            f".{self.path.name}.purge-{os.getpid()}.tmp"
        )
        with temp_path.open("w", encoding="utf-8", newline="\n") as target:
            for line in kept:
                target.write(line)
                target.write("\n")
            target.flush()
            os.fsync(target.fileno())
        os.replace(temp_path, self.path)
        return removed

    def _ensure_append_starts_on_new_line(self) -> None:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return
        with self.path.open("rb") as f:
            f.seek(-1, 2)
            last_byte = f.read(1)
        if last_byte != b"\n":
            with self.path.open("a", encoding="utf-8", newline="\n") as f:
                f.write("\n")


def _hash_body(body: str) -> str:
    digest = hashlib.sha256(str(body).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False, default=str))
