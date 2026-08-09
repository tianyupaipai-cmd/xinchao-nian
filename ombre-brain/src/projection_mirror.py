from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass
class TraceCatalogProjection:
    """Rebuildable shadow projection derived from ledger mirror events."""

    traces: dict[str, dict[str, Any]] = field(default_factory=dict)
    applied_seq: int = 0
    unknown_event_count: int = 0

    def rebuild(self, events: Iterable[dict[str, Any]]) -> None:
        self.traces = {}
        self.applied_seq = 0
        self.unknown_event_count = 0
        for event in events:
            self.apply(event)

    def apply(self, event: dict[str, Any]) -> None:
        try:
            self.applied_seq = max(self.applied_seq, int(event.get("seq", 0)))
        except (TypeError, ValueError):
            pass
        event_type = str(event.get("event_type") or "")
        trace_id = str(event.get("trace_id") or "")
        if not trace_id:
            self.unknown_event_count += 1
            return
        if event_type == "TraceCreated":
            self.traces[trace_id] = _base_trace(event)
            return
        if event_type in {
            "TraceUpdated",
            "TraceTouched",
            "TraceArchived",
            "TraceDeletedToArchive",
            "TraceRestored",
        }:
            trace = self.traces.setdefault(trace_id, _base_trace(event))
            _apply_known_event(trace, event)
            return
        self.unknown_event_count += 1

    def to_report(self, *, source_latest_seq: int = 0) -> dict[str, Any]:
        lag = max(0, int(source_latest_seq or 0) - self.applied_seq)
        return {
            "projection_name": "trace_catalog",
            "projection_role": "shadow",
            "canonical": False,
            "trace_count": len(self.traces),
            "tombstone_count": sum(1 for trace in self.traces.values() if trace.get("tombstone")),
            "applied_seq": self.applied_seq,
            "source_latest_seq": int(source_latest_seq or 0),
            "lag": lag,
            "unknown_event_count": self.unknown_event_count,
        }


def _base_trace(event: dict[str, Any]) -> dict[str, Any]:
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    event_type = str(event.get("event_type") or "")
    trace_kind = str(event.get("trace_kind") or payload.get("type") or "dynamic")
    trace = {
        "trace_id": str(event.get("trace_id") or ""),
        "trace_kind": trace_kind,
        "state": _state_for_event(event),
        "body_hash": str(event.get("body_hash") or ""),
        "created_seq": int(event.get("seq", 0) or 0),
        "latest_seq": int(event.get("seq", 0) or 0),
        "latest_event_type": event_type,
        "touch_count": 0,
        "resolved": bool(payload.get("resolved", False)),
        "deleted": event_type == "TraceDeletedToArchive",
        "tombstone": _is_tombstone_event(event),
        "metadata": dict(payload),
    }
    if event_type == "TraceTouched":
        trace["touch_count"] = 1
    return trace


def _apply_known_event(trace: dict[str, Any], event: dict[str, Any]) -> None:
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    event_type = str(event.get("event_type") or "")
    trace["latest_seq"] = int(event.get("seq", trace.get("latest_seq", 0)) or 0)
    trace["latest_event_type"] = event_type
    trace["body_hash"] = str(event.get("body_hash") or trace.get("body_hash") or "")
    trace["trace_kind"] = str(event.get("trace_kind") or trace.get("trace_kind") or "dynamic")
    trace["state"] = _state_for_event(event)
    trace["metadata"].update(payload)
    if "resolved" in payload:
        trace["resolved"] = bool(payload.get("resolved"))
    if event_type == "TraceTouched":
        trace["touch_count"] = int(trace.get("touch_count", 0) or 0) + 1
    if event_type == "TraceDeletedToArchive":
        trace["deleted"] = True
    if event_type == "TraceRestored":
        trace["deleted"] = False
        trace["tombstone"] = False
    if _is_tombstone_event(event):
        trace["tombstone"] = True


def _state_for_event(event: dict[str, Any]) -> str:
    event_type = str(event.get("event_type") or "")
    trace_kind = str(event.get("trace_kind") or "dynamic")
    if _is_tombstone_event(event):
        return "tombstone"
    if event_type == "TraceDeletedToArchive":
        return "deleted_to_archive"
    if event_type == "TraceRestored":
        return "active"
    if event_type == "TraceArchived" or trace_kind == "archived":
        return "archived"
    return "active"


def _is_tombstone_event(event: dict[str, Any]) -> bool:
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    if bool(payload.get("tombstone")):
        return True
    return str(payload.get("erasure_mode") or "").lower() == "tombstone_only"
