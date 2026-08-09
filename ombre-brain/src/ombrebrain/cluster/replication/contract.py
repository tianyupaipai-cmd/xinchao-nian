from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping


_TRACE_EVENT_TYPES = {
    "TraceCreated",
    "TraceUpdated",
    "TraceTouched",
    "TraceArchived",
    "TraceDeletedToArchive",
    "TombstoneWritten",
    "TraceContentRemoved",
    "ErasedContentRemoved",
}

_CONTENT_REMOVAL_EVENTS = {
    "TraceContentRemoved",
    "ErasedContentRemoved",
    "TracePhysicallyErased",
    "TracePurged",
}

_TOMBSTONE_EVENTS = {
    "TombstoneWritten",
    "TraceDeletedToArchive",
}


@dataclass(frozen=True)
class ReplicationTopology:
    canonical_writers: tuple[str, ...] = ("leader",)
    projection_readers: tuple[str, ...] = ()
    encrypted_replicas: tuple[str, ...] = ()
    segment_mode: str = "snapshot_append_only"
    consensus_mode: str = "single_writer"
    necessity_reason: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "canonical_writers", tuple(str(item) for item in self.canonical_writers))
        object.__setattr__(self, "projection_readers", tuple(str(item) for item in self.projection_readers))
        object.__setattr__(self, "encrypted_replicas", tuple(str(item) for item in self.encrypted_replicas))
        object.__setattr__(self, "segment_mode", _normalize_token(self.segment_mode))
        object.__setattr__(self, "consensus_mode", _normalize_token(self.consensus_mode))
        object.__setattr__(self, "necessity_reason", str(self.necessity_reason or ""))

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_writers": list(self.canonical_writers),
            "projection_readers": list(self.projection_readers),
            "encrypted_replicas": list(self.encrypted_replicas),
            "segment_mode": self.segment_mode,
            "consensus_mode": self.consensus_mode,
            "necessity_reason": self.necessity_reason,
        }


@dataclass(frozen=True)
class ReplicationSegment:
    replica_id: str
    events: tuple[Mapping[str, Any], ...] = ()
    encrypted: bool = False
    segment_kind: str = "append_only_segment"

    def __post_init__(self) -> None:
        object.__setattr__(self, "replica_id", str(self.replica_id or ""))
        object.__setattr__(self, "events", tuple(_json_safe(dict(event)) for event in self.events))
        object.__setattr__(self, "segment_kind", _normalize_token(self.segment_kind))

    def to_dict(self) -> dict[str, Any]:
        return {
            "replica_id": self.replica_id,
            "events": [dict(event) for event in self.events],
            "encrypted": self.encrypted,
            "segment_kind": self.segment_kind,
        }


@dataclass(frozen=True)
class ReplicationDecision:
    ok: bool
    contract_name: str = "replication"
    checked: tuple[str, ...] = ()
    violations: tuple[dict[str, Any], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "checked", tuple(str(item) for item in self.checked))
        object.__setattr__(self, "violations", tuple(_json_safe(dict(item)) for item in self.violations))

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "contract_name": self.contract_name,
            "checked": list(self.checked),
            "violations": [dict(violation) for violation in self.violations],
        }


@dataclass(frozen=True)
class ReplicationContract:
    trace_event_types: frozenset[str] = frozenset(_TRACE_EVENT_TYPES)

    @classmethod
    def default(cls) -> "ReplicationContract":
        return cls()

    def evaluate_topology(self, topology: ReplicationTopology | Mapping[str, Any]) -> ReplicationDecision:
        normalized = _coerce_topology(topology)
        violations: list[dict[str, Any]] = []
        if len(normalized.canonical_writers) != 1:
            violations.append(
                _violation(
                    "multiple_canonical_writers",
                    canonical_writers=list(normalized.canonical_writers),
                    message="cluster replication must use a single-writer canonical ledger",
                )
            )
        if not normalized.projection_readers:
            violations.append(
                _violation(
                    "missing_projection_readers",
                    message="cluster replication should expose multi-reader projections",
                )
            )
        if normalized.segment_mode not in {"snapshot_append_only", "snapshot_append_only_segment"}:
            violations.append(
                _violation(
                    "unsupported_replication_segment_mode",
                    segment_mode=normalized.segment_mode,
                    message="replication should use snapshot + append-only segment replication",
                )
            )
        if normalized.consensus_mode in {"full_distributed_consensus", "full_consensus"} and not normalized.necessity_reason.strip():
            violations.append(
                _violation(
                    "unnecessary_full_consensus",
                    message="do not pretend the project needs full distributed consensus without explicit necessity",
                )
            )
        return self._decision(
            violations,
            checked=(
                "single_writer_canonical_ledger",
                "multi_reader_projections",
                "optional_encrypted_replicas",
                "snapshot_append_only_replication",
            ),
        )

    def evaluate_segment(self, segment: ReplicationSegment | Mapping[str, Any]) -> ReplicationDecision:
        normalized = _coerce_segment(segment)
        violations: list[dict[str, Any]] = []
        tombstoned: set[str] = set()
        removals: set[str] = set()
        for index, event in enumerate(normalized.events):
            event_type = str(event.get("event_type") or event.get("type") or "")
            trace_id = str(event.get("trace_id") or event.get("id") or "")
            payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
            if _is_user_record(event):
                violations.append(
                    _violation(
                        "replicates_user_record",
                        replica_id=normalized.replica_id,
                        index=index,
                        message="replication must copy traces and tombstones, not database-style user records",
                    )
                )
            if event_type in _TOMBSTONE_EVENTS or _truthy(payload.get("tombstone")):
                if trace_id:
                    tombstoned.add(trace_id)
            if event_type in _CONTENT_REMOVAL_EVENTS or _truthy(payload.get("erased_content_removed")):
                if trace_id:
                    removals.add(trace_id)
        for trace_id in sorted(removals - tombstoned):
            violations.append(
                _violation(
                    "content_removal_without_tombstone",
                    replica_id=normalized.replica_id,
                    trace_id=trace_id,
                    message="replica receiving erased content removal must also receive the tombstone",
                )
            )
        return self._decision(
            violations,
            checked=("trace_and_tombstone_replication", "removal_tombstone_pairing"),
        )

    def _decision(self, violations: list[dict[str, Any]], *, checked: tuple[str, ...]) -> ReplicationDecision:
        return ReplicationDecision(ok=not violations, checked=checked, violations=tuple(violations))


def _coerce_topology(value: ReplicationTopology | Mapping[str, Any]) -> ReplicationTopology:
    if isinstance(value, ReplicationTopology):
        return value
    return ReplicationTopology(
        canonical_writers=tuple(value.get("canonical_writers") or ()),
        projection_readers=tuple(value.get("projection_readers") or ()),
        encrypted_replicas=tuple(value.get("encrypted_replicas") or ()),
        segment_mode=str(value.get("segment_mode") or "snapshot_append_only"),
        consensus_mode=str(value.get("consensus_mode") or "single_writer"),
        necessity_reason=str(value.get("necessity_reason") or ""),
    )


def _coerce_segment(value: ReplicationSegment | Mapping[str, Any]) -> ReplicationSegment:
    if isinstance(value, ReplicationSegment):
        return value
    return ReplicationSegment(
        replica_id=str(value.get("replica_id") or ""),
        events=tuple(value.get("events") or ()),
        encrypted=bool(value.get("encrypted", False)),
        segment_kind=str(value.get("segment_kind") or "append_only_segment"),
    )


def _is_user_record(event: Mapping[str, Any]) -> bool:
    record_kind = _normalize_token(event.get("record_kind") or event.get("kind") or "")
    event_type = _normalize_token(event.get("event_type") or event.get("type") or "")
    trace_kind = _normalize_token(event.get("trace_kind") or "")
    return (
        record_kind in {"user_record", "user_profile", "database_user_record"}
        or event_type in {"user_record", "user_profile", "userrow", "user_row"}
        or trace_kind in {"user", "user_record", "profile"}
        or "user_id" in event and "trace_id" not in event
    )


def _truthy(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _normalize_token(value: object) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _violation(code: str, **details: Any) -> dict[str, Any]:
    return {"code": code, **details}


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False, default=str))
