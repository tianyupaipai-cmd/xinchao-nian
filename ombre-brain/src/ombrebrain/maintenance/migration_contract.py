from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any, Iterable, Mapping


_PYTHON_FIRST_PHASES = (
    "ledger_mirror",
    "rebuildable_projections",
    "policy_vm_retrieval",
    "tombstone_only_erasure",
)

_RUST_PHASES = {
    "rust_kernel_extraction",
    "rust_kernel",
    "kernel_extraction",
}


@dataclass(frozen=True)
class MigrationTraceRecord:
    trace_id: str
    trace_kind: str
    state: str = "active"
    lineage: tuple[str, ...] = ()
    decay: Mapping[str, Any] = field(default_factory=dict)
    tombstone: bool = False
    anchor: bool = False
    surfacing_rules: Mapping[str, Any] = field(default_factory=dict)
    target_table: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "trace_id", str(self.trace_id or ""))
        object.__setattr__(self, "trace_kind", _normalize_token(self.trace_kind))
        object.__setattr__(self, "state", _normalize_token(self.state or "active"))
        object.__setattr__(self, "lineage", tuple(str(item) for item in self.lineage))
        object.__setattr__(self, "decay", _json_safe(dict(self.decay)))
        object.__setattr__(self, "surfacing_rules", _json_safe(dict(self.surfacing_rules)))
        object.__setattr__(self, "target_table", _normalize_token(self.target_table or self.trace_kind))

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "trace_kind": self.trace_kind,
            "state": self.state,
            "lineage": list(self.lineage),
            "decay": dict(self.decay),
            "tombstone": self.tombstone,
            "anchor": self.anchor,
            "surfacing_rules": dict(self.surfacing_rules),
            "target_table": self.target_table,
        }


@dataclass(frozen=True)
class MigrationPhasePlan:
    completed_phases: tuple[str, ...] = ()
    startup_prerequisites: tuple[str, ...] = _PYTHON_FIRST_PHASES

    def __post_init__(self) -> None:
        object.__setattr__(self, "completed_phases", tuple(_normalize_token(item) for item in self.completed_phases))
        object.__setattr__(
            self,
            "startup_prerequisites",
            tuple(_normalize_token(item) for item in self.startup_prerequisites),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "completed_phases": list(self.completed_phases),
            "startup_prerequisites": list(self.startup_prerequisites),
        }


@dataclass(frozen=True)
class MigrationContractDecision:
    ok: bool
    contract_name: str = "migration_preservation"
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
class MigrationPreservationContract:
    python_first_phases: tuple[str, ...] = _PYTHON_FIRST_PHASES

    @classmethod
    def default(cls) -> "MigrationPreservationContract":
        return cls()

    def evaluate_records(
        self,
        source_records: Iterable[MigrationTraceRecord | Mapping[str, Any]],
        target_records: Iterable[MigrationTraceRecord | Mapping[str, Any]],
    ) -> MigrationContractDecision:
        source = [_coerce_record(record) for record in source_records]
        target = [_coerce_record(record) for record in target_records]
        target_by_id = {record.trace_id: record for record in target}
        violations: list[dict[str, Any]] = []

        if _looks_flattened(source, target):
            violations.append(
                _violation(
                    "philosophical_distinctions_flattened",
                    message="migration must not flatten dynamic/permanent/archive/anchor into generic memories",
                )
            )

        for source_record in source:
            target_record = target_by_id.get(source_record.trace_id)
            if target_record is None:
                violations.append(_violation("target_trace_missing", trace_id=source_record.trace_id))
                continue
            violations.extend(_record_violations(source_record, target_record))

        return self._decision(
            violations,
            checked=(
                "trace_kind_preserved",
                "state_preserved",
                "lineage_preserved",
                "decay_preserved",
                "tombstone_preserved",
                "anchor_preserved",
                "surfacing_rules_preserved",
            ),
        )

    def evaluate_phase_plan(self, plan: MigrationPhasePlan | Mapping[str, Any]) -> MigrationContractDecision:
        normalized = _coerce_phase_plan(plan)
        completed = set(normalized.completed_phases)
        prerequisites = set(normalized.startup_prerequisites)
        violations: list[dict[str, Any]] = []

        if prerequisites & _RUST_PHASES:
            violations.append(
                _violation(
                    "rust_extraction_as_startup_condition",
                    message="Rust extraction must not be a vNext startup condition",
                )
            )

        for phase in self.python_first_phases:
            if phase not in completed:
                violations.append(
                    _violation(
                        "python_first_phase_missing",
                        phase=phase,
                        message="Python-first migration phase must be available before deeper extraction work",
                    )
                )

        return self._decision(
            violations,
            checked=("python_first_phases", "rust_not_startup_condition"),
        )

    def _decision(self, violations: list[dict[str, Any]], *, checked: tuple[str, ...]) -> MigrationContractDecision:
        return MigrationContractDecision(ok=not violations, checked=checked, violations=tuple(violations))


def _record_violations(source: MigrationTraceRecord, target: MigrationTraceRecord) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    if source.trace_kind != target.trace_kind:
        violations.append(
            _violation(
                "trace_kind_not_preserved",
                trace_id=source.trace_id,
                source=source.trace_kind,
                target=target.trace_kind,
            )
        )
    if source.state != target.state:
        violations.append(
            _violation(
                "state_not_preserved",
                trace_id=source.trace_id,
                source=source.state,
                target=target.state,
            )
        )
    if source.lineage and tuple(source.lineage) != tuple(target.lineage):
        violations.append(_violation("lineage_not_preserved", trace_id=source.trace_id))
    if source.decay and dict(source.decay) != dict(target.decay):
        violations.append(_violation("decay_not_preserved", trace_id=source.trace_id))
    if bool(source.tombstone) != bool(target.tombstone):
        violations.append(_violation("tombstone_not_preserved", trace_id=source.trace_id))
    if bool(source.anchor) != bool(target.anchor):
        violations.append(_violation("anchor_not_preserved", trace_id=source.trace_id))
    if source.surfacing_rules and dict(source.surfacing_rules) != dict(target.surfacing_rules):
        violations.append(_violation("surfacing_rules_not_preserved", trace_id=source.trace_id))
    return violations


def _looks_flattened(source: list[MigrationTraceRecord], target: list[MigrationTraceRecord]) -> bool:
    if len(source) < 2 or not target:
        return False
    source_kinds = {record.trace_kind for record in source}
    source_has_anchor = any(record.anchor for record in source)
    target_kinds = {record.trace_kind for record in target}
    target_tables = {record.target_table for record in target}
    return (
        (len(source_kinds) > 1 or source_has_anchor)
        and len(target_kinds) == 1
        and target_kinds <= {"memory", "memories"}
        and target_tables <= {"memory", "memories"}
    )


def _coerce_record(value: MigrationTraceRecord | Mapping[str, Any]) -> MigrationTraceRecord:
    if isinstance(value, MigrationTraceRecord):
        return value
    return MigrationTraceRecord(
        trace_id=str(value.get("trace_id") or value.get("id") or ""),
        trace_kind=str(value.get("trace_kind") or value.get("type") or ""),
        state=str(value.get("state") or "active"),
        lineage=tuple(value.get("lineage") or ()),
        decay=value.get("decay") if isinstance(value.get("decay"), Mapping) else {},
        tombstone=bool(value.get("tombstone")),
        anchor=bool(value.get("anchor")),
        surfacing_rules=value.get("surfacing_rules") if isinstance(value.get("surfacing_rules"), Mapping) else {},
        target_table=str(value.get("target_table") or value.get("table") or ""),
    )


def _coerce_phase_plan(value: MigrationPhasePlan | Mapping[str, Any]) -> MigrationPhasePlan:
    if isinstance(value, MigrationPhasePlan):
        return value
    return MigrationPhasePlan(
        completed_phases=tuple(value.get("completed_phases") or ()),
        startup_prerequisites=tuple(value.get("startup_prerequisites") or ()),
    )


def _normalize_token(value: object) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _violation(code: str, **details: Any) -> dict[str, Any]:
    return {"code": code, **details}


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False, default=str))
