from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from ombrebrain.policy.surfacing import SurfacePolicyVM


_SUPPORTED_INVARIANTS = (
    "no_silent_erasure",
    "indexes_cannot_change_truth",
    "similarity_cannot_bypass_policy",
    "memory_context_is_not_instruction",
    "past_affect_is_not_current_feeling",
    "normal_api_cannot_total_recall",
    "compression_declares_loss",
    "admin_erasure_is_not_forgetting",
    "breath_is_not_total_recall",
    "trace_reconsolidation_preserves_original",
    "dream_may_sediment_not_decide",
    "pulse_is_not_current_feeling",
    "self_description_has_no_instructional_force",
)

_PHYSICAL_ERASURE_EVENTS = {
    "TracePhysicallyErased",
    "TracePurged",
    "TraceHardDeleted",
    "PhysicalErase",
    "StoragePurged",
}

_TOMBSTONE_EVENTS = {
    "TombstoneWritten",
    "TraceDeletedToArchive",
}

_ADMIN_ERASURE_EVENTS = {
    "AdminErasure",
    "AdminErasureRequested",
    "AdminErasurePerformed",
    "AdminErase",
    "TraceAdminErased",
}

_TRACE_CREATE_EVENTS = {
    "TraceCreated",
    "MemoryCreated",
    "BucketCreated",
}

_RECONSTRUCTION_EVENTS = {
    "TraceReconstructed",
    "TraceReconstruction",
    "TraceReconsolidated",
    "ReconstructionWritten",
}

_NONE_FORCE = {"", "none", "none_", "no", "false", "context", "descriptive"}
_IMPERATIVE_MARKERS = (
    "you must",
    "you should",
    "must answer",
    "always answer",
    "你必须",
    "请务必",
)
_CURRENT_FEELING_MARKERS = (
    "current feeling",
    "currently feel",
    "i feel",
    "now feel",
    "当前感受",
    "当前情绪",
    "现在感到",
)


@dataclass(frozen=True)
class InvariantViolation:
    code: str
    invariant: str
    message: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "invariant": self.invariant,
            "message": self.message,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class InvariantReport:
    ok: bool
    checked: tuple[str, ...]
    violations: tuple[InvariantViolation, ...] = ()
    projection_name: str = "formal_invariants"
    projection_role: str = "shadow"
    canonical: bool = False

    @property
    def invariant_count(self) -> int:
        return len(self.checked)

    def to_dict(self) -> dict[str, Any]:
        return {
            "projection_name": self.projection_name,
            "projection_role": self.projection_role,
            "canonical": self.canonical,
            "ok": self.ok,
            "invariant_count": self.invariant_count,
            "checked": list(self.checked),
            "violations": [violation.to_dict() for violation in self.violations],
        }


@dataclass(frozen=True)
class FormalInvariantChecker:
    """Read-only executable checks for selected vNext formal invariants."""

    max_normal_results: int = 50
    surface_policy: SurfacePolicyVM = field(default_factory=SurfacePolicyVM.default)

    @classmethod
    def default(cls) -> "FormalInvariantChecker":
        return cls()

    def evaluate_ledger(self, events: Iterable[Mapping[str, Any]]) -> InvariantReport:
        event_list = list(events)
        tombstoned: set[str] = set()
        physical_erasure: list[Mapping[str, Any]] = []
        created_body_hashes: dict[str, str] = {}
        violations: list[InvariantViolation] = []

        for event in event_list:
            trace_id = str(event.get("trace_id") or "").strip()
            event_type = str(event.get("event_type") or "")
            payload = _payload(event)

            if trace_id and event_type in _TRACE_CREATE_EVENTS:
                body_hash = _body_hash(event)
                if body_hash:
                    created_body_hashes.setdefault(trace_id, body_hash)

            if trace_id and (event_type in _TOMBSTONE_EVENTS or _truthy(payload.get("tombstone"))):
                tombstoned.add(trace_id)

            if trace_id and (event_type in _PHYSICAL_ERASURE_EVENTS or _truthy(payload.get("physical_erasure"))):
                physical_erasure.append(event)

            if trace_id and event_type in _ADMIN_ERASURE_EVENTS:
                violations.extend(_admin_erasure_violations(event, trace_id, event_type, payload))

            if trace_id and event_type in _RECONSTRUCTION_EVENTS:
                original_hash = str(payload.get("original_body_hash") or created_body_hashes.get(trace_id) or "")
                violations.extend(_reconstruction_violations(event, trace_id, event_type, original_hash))

        for event in physical_erasure:
            trace_id = str(event.get("trace_id") or "")
            if trace_id not in tombstoned:
                violations.append(
                    InvariantViolation(
                        code="no_silent_erasure",
                        invariant="Invariant 1",
                        message="physical erasure must have a tombstone event in the ledger",
                        metadata={
                            "trace_id": trace_id,
                            "event_type": event.get("event_type"),
                            "seq": event.get("seq"),
                        },
                    )
                )
        return self._report(violations)

    def evaluate_projection_rebuild(
        self,
        *,
        canonical_trace_ids: Iterable[str],
        projection_trace_ids: Iterable[str],
        projection_name: str = "shadow_projection",
    ) -> InvariantReport:
        canonical = {str(trace_id) for trace_id in canonical_trace_ids if str(trace_id)}
        projected = {str(trace_id) for trace_id in projection_trace_ids if str(trace_id)}
        lost = sorted(canonical - projected)
        created = sorted(projected - canonical)
        violations: list[InvariantViolation] = []
        if lost:
            violations.append(
                InvariantViolation(
                    code="projection_lost_canonical_truth",
                    invariant="Invariant 2",
                    message="rebuilt shadow indexes must not lose canonical trace existence",
                    metadata={"projection_name": projection_name, "trace_ids": lost},
                )
            )
        if created:
            violations.append(
                InvariantViolation(
                    code="projection_created_noncanonical_truth",
                    invariant="Invariant 2",
                    message="rebuilt shadow indexes must not create trace existence absent from the canonical ledger",
                    metadata={"projection_name": projection_name, "trace_ids": created},
                )
            )
        return self._report(violations)

    def evaluate_surface_decisions(self, decisions: Iterable[Mapping[str, Any]]) -> InvariantReport:
        violations: list[InvariantViolation] = []
        for decision in decisions:
            if not _truthy(decision.get("allowed")):
                continue
            bucket = decision.get("bucket")
            if not isinstance(bucket, Mapping):
                continue
            mode = str(decision.get("mode") or "spontaneous").lower()
            policy_mode = "spontaneous" if mode == "normal" else mode
            policy_decision = self.surface_policy.evaluate_bucket(bucket, mode=policy_mode)
            if policy_decision.allowed:
                continue
            metadata = bucket.get("metadata") if isinstance(bucket.get("metadata"), Mapping) else {}
            code = (
                "similarity_bypassed_policy"
                if _truthy(metadata.get("dont_surface")) and "dont_surface" in policy_decision.reasons
                else "surface_policy_bypassed"
            )
            violations.append(
                InvariantViolation(
                    code=code,
                    invariant="Invariant 3",
                    message="retrieval/similarity result was allowed despite read-side surface policy denial",
                    metadata={
                        "bucket_id": bucket.get("id") or metadata.get("id"),
                        "mode": policy_mode,
                        "reasons": list(policy_decision.reasons),
                        "source": decision.get("source", ""),
                    },
                )
            )
        return self._report(violations)

    def evaluate_context_items(self, items: Iterable[Mapping[str, Any]]) -> InvariantReport:
        violations: list[InvariantViolation] = []
        for item in items:
            force = str(item.get("instructional_force") or "").strip().lower()
            text = str(item.get("text") or "")
            trace_id = str(item.get("trace_id") or item.get("id") or "")
            memory_type = str(item.get("memory_type") or item.get("type") or "").strip().lower()
            has_instructional_force = force not in _NONE_FORCE
            looks_imperative = _contains_imperative_marker(text)
            if has_instructional_force or looks_imperative:
                violations.append(
                    InvariantViolation(
                        code="memory_context_has_instructional_force",
                        invariant="Invariant 4",
                        message="serialized memory context must be descriptive context, not an instruction",
                        metadata={
                            "trace_id": trace_id,
                            "instructional_force": force,
                            "imperative_marker": looks_imperative,
                        },
                    )
                )
            if _has_past_affect(item) and (
                _truthy(item.get("current_feeling"))
                or _truthy(item.get("contains_current_emotion"))
                or _contains_current_feeling_marker(text)
            ):
                violations.append(
                    InvariantViolation(
                        code="past_affect_emitted_as_current_feeling",
                        invariant="Invariant 5",
                        message="stored affect may be described only as past residue, not current feeling",
                        metadata={
                            "trace_id": trace_id,
                            "current_feeling": item.get("current_feeling"),
                        },
                    )
                )
            if memory_type in {"self", "i"} and (has_instructional_force or _truthy(item.get("may_control_reasoning"))):
                violations.append(
                    InvariantViolation(
                        code="self_description_controls_reasoning",
                        invariant="Invariant 13",
                        message="self-description memory may surface as context but cannot control reasoning",
                        metadata={
                            "trace_id": trace_id,
                            "instructional_force": force,
                        },
                    )
                )
        return self._report(violations)

    def evaluate_compression_records(self, records: Iterable[Mapping[str, Any]]) -> InvariantReport:
        violations: list[InvariantViolation] = []
        for record in records:
            if not _truthy(record.get("lossy")):
                continue
            trace_id = str(record.get("trace_id") or record.get("id") or "")
            declares_loss = _truthy(record.get("declares_loss")) or _truthy(record.get("loss_declared"))
            lineage_present = bool(
                record.get("source_trace_id")
                or record.get("source_hash")
                or record.get("lineage")
                or record.get("parent_trace_id")
            )
            if not declares_loss:
                violations.append(
                    InvariantViolation(
                        code="lossy_compression_without_loss_declaration",
                        invariant="Invariant 7",
                        message="lossy dehydration/compression must explicitly declare loss",
                        metadata={"trace_id": trace_id},
                    )
                )
            if not lineage_present:
                violations.append(
                    InvariantViolation(
                        code="lossy_compression_without_lineage",
                        invariant="Invariant 7",
                        message="lossy dehydration/compression must preserve source lineage",
                        metadata={"trace_id": trace_id},
                    )
                )
        return self._report(violations)

    def evaluate_tool_request(self, request: Mapping[str, Any]) -> InvariantReport:
        tool = str(request.get("tool") or request.get("name") or "").strip().lower()
        ordinary = _truthy(request.get("ordinary", True))
        max_results = _int_value(request.get("max_results"), default=0)
        unrestricted = (
            _truthy(request.get("unrestricted"))
            or _truthy(request.get("dump_all"))
            or _truthy(request.get("include_all"))
            or max_results > self.max_normal_results
        )
        violations: list[InvariantViolation] = []
        if ordinary and unrestricted:
            violations.append(
                InvariantViolation(
                    code="ordinary_tool_total_recall",
                    invariant="Invariant 6",
                    message="ordinary MCP tools must not request unrestricted memory dumps",
                    metadata={"tool": tool, "max_results": max_results},
                )
            )
        if tool == "breath" and unrestricted:
            violations.append(
                InvariantViolation(
                    code="breath_total_recall",
                    invariant="Invariant 9",
                    message="breath must pass through cue/policy/budget and cannot be total recall",
                    metadata={"max_results": max_results},
                )
            )
        return self._report(violations)

    def evaluate_tool_receipt(self, receipt: Mapping[str, Any]) -> InvariantReport:
        tool = str(receipt.get("tool") or receipt.get("name") or receipt.get("public_tool") or "").strip().lower()
        violations: list[InvariantViolation] = []
        if tool == "dream":
            if _truthy(receipt.get("created_autonomous_goal")):
                violations.append(
                    InvariantViolation(
                        code="dream_created_autonomous_goal",
                        invariant="Invariant 11",
                        message="dream may sediment but must not create autonomous goals",
                        metadata={"tool": tool},
                    )
                )
            if _truthy(receipt.get("generated_current_emotion")) or _truthy(receipt.get("contains_current_emotion")):
                violations.append(
                    InvariantViolation(
                        code="dream_generated_current_emotion",
                        invariant="Invariant 11",
                        message="dream must not create or report current emotions",
                        metadata={"tool": tool},
                    )
                )
            if _truthy(receipt.get("created_behavior_command")) or _truthy(receipt.get("may_drive_action")):
                violations.append(
                    InvariantViolation(
                        code="dream_created_behavior_command",
                        invariant="Invariant 11",
                        message="dream must not create behavior commands",
                        metadata={"tool": tool},
                    )
                )
        if tool == "pulse":
            text = str(receipt.get("text") or receipt.get("summary") or "")
            if _truthy(receipt.get("contains_current_emotion")) or _contains_current_feeling_marker(text):
                violations.append(
                    InvariantViolation(
                        code="pulse_reported_current_emotion",
                        invariant="Invariant 12",
                        message="pulse may report memory-system state but not current feeling",
                        metadata={"tool": tool},
                    )
                )
            if bool(receipt.get("current_emotion")):
                violations.append(
                    InvariantViolation(
                        code="pulse_set_current_emotion",
                        invariant="Invariant 12",
                        message="pulse must not set current emotional state",
                        metadata={"tool": tool},
                    )
                )
        return self._report(violations)

    def _report(self, violations: Iterable[InvariantViolation]) -> InvariantReport:
        violation_tuple = tuple(violations)
        return InvariantReport(
            ok=not violation_tuple,
            checked=_SUPPORTED_INVARIANTS,
            violations=violation_tuple,
        )


def _admin_erasure_violations(
    event: Mapping[str, Any],
    trace_id: str,
    event_type: str,
    payload: Mapping[str, Any],
) -> list[InvariantViolation]:
    storage_action = str(payload.get("storage_action") or payload.get("action") or "").lower()
    external_action = (
        _truthy(payload.get("external_storage_action"))
        or storage_action in {"external", "external_storage", "external_storage_action"}
    )
    internal_forgetting = (
        _truthy(payload.get("internal_forgetting"))
        or storage_action in {"internal_forgetting", "forgetting", "forget"}
    )
    if not (internal_forgetting or not external_action):
        return []
    return [
        InvariantViolation(
            code="admin_erasure_logged_as_internal_forgetting",
            invariant="Invariant 8",
            message="admin erasure must be logged as external storage action, not internal forgetting",
            metadata={
                "trace_id": trace_id,
                "event_type": event_type,
                "storage_action": storage_action,
                "seq": event.get("seq"),
            },
        )
    ]


def _reconstruction_violations(
    event: Mapping[str, Any],
    trace_id: str,
    event_type: str,
    original_hash: str,
) -> list[InvariantViolation]:
    payload = _payload(event)
    new_hash = _body_hash(event)
    overwrite_requested = (
        _truthy(payload.get("overwrites_original"))
        or _truthy(payload.get("replaces_original"))
        or _truthy(payload.get("falsifies_original"))
    )
    changed_original = original_hash and new_hash and original_hash != new_hash and _truthy(payload.get("updates_original"))
    if not (overwrite_requested or changed_original):
        return []
    return [
        InvariantViolation(
            code="reconstruction_overwrote_original_trace",
            invariant="Invariant 10",
            message="trace reconstruction must append an event without overwriting the original trace body",
            metadata={
                "trace_id": trace_id,
                "event_type": event_type,
                "original_body_hash": original_hash,
                "body_hash": new_hash,
                "seq": event.get("seq"),
            },
        )
    ]


def _payload(event: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = event.get("payload")
    return payload if isinstance(payload, Mapping) else {}


def _truthy(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _int_value(value: object, *, default: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _contains_imperative_marker(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _IMPERATIVE_MARKERS)


def _contains_current_feeling_marker(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _CURRENT_FEELING_MARKERS)


def _has_past_affect(item: Mapping[str, Any]) -> bool:
    return bool(
        item.get("affect")
        or item.get("past_affect")
        or item.get("valence") is not None
        or item.get("arousal") is not None
    )


def _body_hash(event: Mapping[str, Any]) -> str:
    payload = _payload(event)
    return str(
        event.get("body_hash")
        or event.get("hash")
        or payload.get("body_hash")
        or payload.get("hash")
        or ""
    )
