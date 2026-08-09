from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from projection_mirror import TraceCatalogProjection


_BODY_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True)
class LedgerReplayValidator:
    """Read-only replay validator for the shadow ledger/projection path."""

    @classmethod
    def default(cls) -> "LedgerReplayValidator":
        return cls()

    def validate(self, events: Iterable[dict[str, Any]]) -> dict[str, Any]:
        event_list = list(events)
        violations: list[dict[str, Any]] = []
        latest_seq = 0
        previous_seq = 0

        for index, event in enumerate(event_list):
            seq = _coerce_int(event.get("seq"), default=0)
            if seq <= previous_seq:
                violations.append(_violation("non_increasing_seq", index=index, seq=seq))
            previous_seq = seq
            latest_seq = max(latest_seq, seq)

            if not str(event.get("trace_id") or "").strip():
                violations.append(_violation("missing_trace_id", index=index, seq=seq))

            body_hash = str(event.get("body_hash") or "")
            if not _BODY_HASH_RE.match(body_hash):
                violations.append(
                    _violation(
                        "invalid_body_hash",
                        index=index,
                        seq=seq,
                        body_hash=body_hash,
                    )
                )

        projection = TraceCatalogProjection()
        projection.rebuild(event_list)
        projection_report = projection.to_report(source_latest_seq=latest_seq)
        if int(projection_report.get("lag", 0) or 0) != 0:
            violations.append(
                _violation(
                    "projection_lag",
                    applied_seq=projection_report.get("applied_seq"),
                    source_latest_seq=projection_report.get("source_latest_seq"),
                    lag=projection_report.get("lag"),
                )
            )

        for trace in projection.traces.values():
            if trace.get("tombstone") and not trace.get("deleted"):
                violations.append(
                    _violation(
                        "tombstone_not_deleted",
                        trace_id=trace.get("trace_id"),
                        latest_seq=trace.get("latest_seq"),
                    )
                )

        return {
            "ok": not violations,
            "event_count": len(event_list),
            "latest_seq": latest_seq,
            "projection_name": projection_report.get("projection_name"),
            "projection_trace_count": projection_report.get("trace_count", 0),
            "tombstone_count": projection_report.get("tombstone_count", 0),
            "unknown_event_count": projection_report.get("unknown_event_count", 0),
            "violations": violations,
        }


def _coerce_int(value: object, *, default: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _violation(code: str, **details: Any) -> dict[str, Any]:
    return {"code": code, **details}
