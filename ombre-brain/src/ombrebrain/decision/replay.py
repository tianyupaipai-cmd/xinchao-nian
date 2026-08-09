from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ombrebrain.decision.records import DecisionRecord


@dataclass(frozen=True)
class ReplayResult:
    ok: bool
    issues: tuple[str, ...]
    explanation: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "issues": list(self.issues),
            "explanation": dict(self.explanation),
        }


@dataclass(frozen=True)
class ReplayDebugger:
    @classmethod
    def default(cls) -> "ReplayDebugger":
        return cls()

    def replay(self, record: DecisionRecord | dict[str, Any]) -> ReplayResult:
        decision = record if isinstance(record, DecisionRecord) else DecisionRecord.from_dict(record)
        issues = list(self._identity_issues(decision))
        issues.extend(self._command_id_issues(decision))
        issues.extend(self._surface_issues(decision))
        explanation = self.explain(decision, issues)
        return ReplayResult(ok=not issues, issues=tuple(issues), explanation=explanation)

    def explain(self, record: DecisionRecord, issues: list[str] | None = None) -> dict[str, Any]:
        policy = _as_dict(record.policy_verdict)
        consistency = _as_dict(record.consistency_report)
        outcome = _as_dict(record.outcome)
        projection_surfaces = sorted(
            _surfaces(_as_list(_as_dict(record.command_plan).get("projections")))
            | _surfaces(_as_list(_as_dict(record.projection_journal).get("entries")))
        )
        return {
            "decision_id": record.id,
            "command_id": record.command_id,
            "module": record.module,
            "operation": record.operation,
            "policy_allowed": bool(policy.get("allowed", True)),
            "missing_permissions": list(_as_list(policy.get("missing_permissions"))),
            "protected_surfaces": list(_as_list(policy.get("protected_surfaces"))),
            "consistency_ok": bool(consistency.get("ok", True)),
            "projection_surfaces": projection_surfaces,
            "outcome_ok": bool(outcome.get("ok", True)),
            "replay_ok": not issues,
            "issue_count": len(issues or []),
        }

    def _identity_issues(self, record: DecisionRecord) -> tuple[str, ...]:
        if record.id == record.canonical_id():
            return ()
        return ("decision id does not match canonical record contents",)

    def _command_id_issues(self, record: DecisionRecord) -> tuple[str, ...]:
        issues: list[str] = []
        command_id = record.command_id
        policy_command_id = _as_dict(_as_dict(record.policy_verdict).get("contract")).get("command_id")
        journal_command_id = _as_dict(record.projection_journal).get("command_id")
        observations_command_id = _as_dict(record.projection_observations).get("command_id")
        consistency_command_id = _as_dict(record.consistency_report).get("command_id")
        for label, candidate in (
            ("policy contract", policy_command_id),
            ("projection journal", journal_command_id),
            ("projection observations", observations_command_id),
            ("consistency report", consistency_command_id),
        ):
            if candidate and str(candidate) != command_id:
                issues.append(f"{label} command id mismatch: expected {command_id}, observed {candidate}")
        return tuple(issues)

    def _surface_issues(self, record: DecisionRecord) -> tuple[str, ...]:
        plan_surfaces = _surfaces(_as_list(_as_dict(record.command_plan).get("projections")))
        journal_surfaces = _surfaces(_as_list(_as_dict(record.projection_journal).get("entries")))
        observation_surfaces = _surfaces(_as_list(_as_dict(record.projection_observations).get("observations")))
        issues: list[str] = []
        if plan_surfaces and journal_surfaces and plan_surfaces != journal_surfaces:
            issues.append(
                "projection surface mismatch between command plan and journal: "
                f"expected {sorted(plan_surfaces)}, observed {sorted(journal_surfaces)}"
            )
        if plan_surfaces and observation_surfaces and not observation_surfaces.issubset(plan_surfaces):
            issues.append(
                "projection observation surface mismatch: "
                f"expected subset of {sorted(plan_surfaces)}, observed {sorted(observation_surfaces)}"
            )
        return tuple(issues)


def _surfaces(entries: list[Any]) -> set[str]:
    surfaces: set[str] = set()
    for entry in entries:
        if isinstance(entry, dict) and entry.get("surface"):
            surfaces.add(str(entry["surface"]))
    return surfaces


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
