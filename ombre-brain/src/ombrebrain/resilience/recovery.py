from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any, Iterable, Mapping


_WRITE_PATH_ORDER = (
    "mcp_tool_call",
    "policy_preflight",
    "append_event_to_wal",
    "fsync",
    "update_projections_async",
    "update_markdown_vault_projection",
    "return_trace_id",
)

_READ_PATH_ORDER = (
    "query",
    "candidate_generation_from_shadow_indexes",
    "canonical_trace_verification",
    "policy_gate",
    "surfacing_budget",
    "context_compiler",
)


@dataclass(frozen=True)
class PathStep:
    name: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _normalize_step(self.name))
        object.__setattr__(self, "metadata", _json_safe(dict(self.metadata)))

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "metadata": dict(self.metadata)}


@dataclass(frozen=True)
class CrashRecoveryPlan:
    ledger_wins: bool = True
    projections_rebuild: bool = True
    markdown_repaired: bool = True
    indexes_disposable: bool = True
    canonical_source: str = "ledger"

    def __post_init__(self) -> None:
        object.__setattr__(self, "canonical_source", _normalize_step(self.canonical_source))

    def to_dict(self) -> dict[str, Any]:
        return {
            "ledger_wins": self.ledger_wins,
            "projections_rebuild": self.projections_rebuild,
            "markdown_repaired": self.markdown_repaired,
            "indexes_disposable": self.indexes_disposable,
            "canonical_source": self.canonical_source,
        }


@dataclass(frozen=True)
class CrashRecoveryDecision:
    ok: bool
    contract_name: str = "crash_recovery"
    recovery_rule: str = "ledger_wins"
    checked: tuple[str, ...] = ()
    violations: tuple[dict[str, Any], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "checked", tuple(str(item) for item in self.checked))
        object.__setattr__(self, "violations", tuple(_json_safe(dict(item)) for item in self.violations))

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "contract_name": self.contract_name,
            "recovery_rule": self.recovery_rule,
            "checked": list(self.checked),
            "violations": [dict(violation) for violation in self.violations],
        }


@dataclass(frozen=True)
class CrashRecoveryContract:
    write_path_order: tuple[str, ...] = _WRITE_PATH_ORDER
    read_path_order: tuple[str, ...] = _READ_PATH_ORDER

    @classmethod
    def default(cls) -> "CrashRecoveryContract":
        return cls()

    def evaluate_write_path(self, steps: Iterable[PathStep | str | Mapping[str, Any]]) -> CrashRecoveryDecision:
        normalized_steps = _coerce_steps(steps)
        violations = _evaluate_order(normalized_steps, self.write_path_order, path_name="write")
        names = [step.name for step in normalized_steps]
        if _appears_before(names, "return_trace_id", "fsync"):
            violations.append(
                _violation(
                    "write_returned_before_fsync",
                    message="write path must fsync WAL before returning trace id",
                )
            )
        if _appears_before(names, "update_projections_async", "fsync"):
            violations.append(
                _violation(
                    "projection_updated_before_fsync",
                    message="projections must update only after WAL fsync",
                )
            )
        return self._decision(violations, checked=self.write_path_order)

    def evaluate_read_path(self, steps: Iterable[PathStep | str | Mapping[str, Any]]) -> CrashRecoveryDecision:
        normalized_steps = _coerce_steps(steps)
        violations = _evaluate_order(normalized_steps, self.read_path_order, path_name="read")
        names = [step.name for step in normalized_steps]
        if _appears_before(names, "policy_gate", "canonical_trace_verification"):
            violations.append(
                _violation(
                    "policy_gate_before_canonical_verification",
                    message="read path must verify canonical trace existence before policy gate",
                )
            )
        return self._decision(violations, checked=self.read_path_order)

    def evaluate_recovery_plan(self, plan: CrashRecoveryPlan | Mapping[str, Any]) -> CrashRecoveryDecision:
        normalized = _coerce_plan(plan)
        violations: list[dict[str, Any]] = []
        if not normalized.ledger_wins:
            violations.append(_violation("ledger_not_declared_winner", canonical_source=normalized.canonical_source))
        if normalized.canonical_source != "ledger":
            violations.append(
                _violation(
                    "projection_treated_as_canonical",
                    canonical_source=normalized.canonical_source,
                    message="crash recovery must treat ledger as the winning source",
                )
            )
        if not normalized.projections_rebuild:
            violations.append(_violation("projections_not_rebuilt"))
        if not normalized.markdown_repaired:
            violations.append(_violation("markdown_not_repaired"))
        if not normalized.indexes_disposable:
            violations.append(_violation("indexes_not_disposable"))
        return self._decision(
            violations,
            checked=(
                "ledger_wins",
                "projections_rebuild",
                "markdown_repaired",
                "indexes_disposable",
            ),
        )

    def _decision(self, violations: list[dict[str, Any]], *, checked: tuple[str, ...]) -> CrashRecoveryDecision:
        return CrashRecoveryDecision(ok=not violations, checked=checked, violations=tuple(violations))


def _evaluate_order(steps: list[PathStep], required_order: tuple[str, ...], *, path_name: str) -> list[dict[str, Any]]:
    names = [step.name for step in steps]
    violations: list[dict[str, Any]] = []
    positions = {name: index for index, name in enumerate(names)}
    for required in required_order:
        if required not in positions:
            violations.append(_violation("missing_path_step", path=path_name, step=required))
    last_index = -1
    for required in required_order:
        if required not in positions:
            continue
        current_index = positions[required]
        if current_index < last_index:
            violations.append(
                _violation(
                    "path_step_out_of_order",
                    path=path_name,
                    step=required,
                    expected_order=list(required_order),
                    actual_order=names,
                )
            )
            break
        last_index = current_index
    return violations


def _coerce_steps(steps: Iterable[PathStep | str | Mapping[str, Any]]) -> list[PathStep]:
    result: list[PathStep] = []
    for step in steps:
        if isinstance(step, PathStep):
            result.append(step)
        elif isinstance(step, Mapping):
            result.append(PathStep(str(step.get("name") or step.get("step") or ""), metadata=step))
        else:
            result.append(PathStep(str(step)))
    return result


def _coerce_plan(plan: CrashRecoveryPlan | Mapping[str, Any]) -> CrashRecoveryPlan:
    if isinstance(plan, CrashRecoveryPlan):
        return plan
    return CrashRecoveryPlan(
        ledger_wins=bool(plan.get("ledger_wins", True)),
        projections_rebuild=bool(plan.get("projections_rebuild", True)),
        markdown_repaired=bool(plan.get("markdown_repaired", True)),
        indexes_disposable=bool(plan.get("indexes_disposable", True)),
        canonical_source=str(plan.get("canonical_source") or "ledger"),
    )


def _appears_before(names: list[str], first: str, second: str) -> bool:
    try:
        return names.index(first) < names.index(second)
    except ValueError:
        return False


def _normalize_step(value: object) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _violation(code: str, **details: Any) -> dict[str, Any]:
    return {"code": code, **details}


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False, default=str))
