from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any


@dataclass(frozen=True)
class DecisionRecord:
    id: str
    command_id: str
    module: str
    operation: str
    command_plan: dict[str, Any]
    policy_verdict: dict[str, Any]
    projection_journal: dict[str, Any]
    projection_observations: dict[str, Any]
    consistency_report: dict[str, Any]
    outcome: dict[str, Any]
    summary: dict[str, Any]
    created_at: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", str(self.id))
        object.__setattr__(self, "command_id", str(self.command_id))
        object.__setattr__(self, "module", str(self.module))
        object.__setattr__(self, "operation", str(self.operation))
        object.__setattr__(self, "command_plan", _json_safe(self.command_plan))
        object.__setattr__(self, "policy_verdict", _json_safe(self.policy_verdict))
        object.__setattr__(self, "projection_journal", _json_safe(self.projection_journal))
        object.__setattr__(self, "projection_observations", _json_safe(self.projection_observations))
        object.__setattr__(self, "consistency_report", _json_safe(self.consistency_report))
        object.__setattr__(self, "outcome", _json_safe(self.outcome))
        object.__setattr__(self, "summary", _json_safe(self.summary))
        object.__setattr__(self, "created_at", str(self.created_at))

    @classmethod
    def new(
        cls,
        *,
        module: str,
        operation: str,
        command_plan: dict[str, Any],
        policy_verdict: dict[str, Any],
        projection_journal: dict[str, Any],
        projection_observations: dict[str, Any],
        consistency_report: dict[str, Any],
        outcome: dict[str, Any],
        created_at: str | None = None,
    ) -> "DecisionRecord":
        payload = {
            "module": str(module),
            "operation": str(operation),
            "command_plan": _json_safe(command_plan),
            "policy_verdict": _json_safe(policy_verdict),
            "projection_journal": _json_safe(projection_journal),
            "projection_observations": _json_safe(projection_observations),
            "consistency_report": _json_safe(consistency_report),
            "outcome": _json_safe(outcome),
        }
        command_id = _extract_command_id(payload)
        return cls(
            id=_stable_id(command_id, payload),
            command_id=command_id,
            module=payload["module"],
            operation=payload["operation"],
            command_plan=payload["command_plan"],
            policy_verdict=payload["policy_verdict"],
            projection_journal=payload["projection_journal"],
            projection_observations=payload["projection_observations"],
            consistency_report=payload["consistency_report"],
            outcome=payload["outcome"],
            summary=_summary(command_id, payload),
            created_at=str(created_at or _created_at(payload)),
        )

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "DecisionRecord":
        data = _json_safe(value)
        payload = {
            "module": str(data.get("module", "")),
            "operation": str(data.get("operation", "")),
            "command_plan": _as_dict(data.get("command_plan")),
            "policy_verdict": _as_dict(data.get("policy_verdict")),
            "projection_journal": _as_dict(data.get("projection_journal")),
            "projection_observations": _as_dict(data.get("projection_observations")),
            "consistency_report": _as_dict(data.get("consistency_report")),
            "outcome": _as_dict(data.get("outcome")),
        }
        command_id = str(data.get("command_id") or _extract_command_id(payload))
        return cls(
            id=str(data.get("id") or _stable_id(command_id, payload)),
            command_id=command_id,
            module=payload["module"],
            operation=payload["operation"],
            command_plan=payload["command_plan"],
            policy_verdict=payload["policy_verdict"],
            projection_journal=payload["projection_journal"],
            projection_observations=payload["projection_observations"],
            consistency_report=payload["consistency_report"],
            outcome=payload["outcome"],
            summary=_summary(command_id, payload),
            created_at=str(data.get("created_at") or _created_at(payload)),
        )

    def canonical_id(self) -> str:
        return _stable_id(
            self.command_id,
            {
                "module": self.module,
                "operation": self.operation,
                "command_plan": self.command_plan,
                "policy_verdict": self.policy_verdict,
                "projection_journal": self.projection_journal,
                "projection_observations": self.projection_observations,
                "consistency_report": self.consistency_report,
                "outcome": self.outcome,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "command_id": self.command_id,
            "module": self.module,
            "operation": self.operation,
            "created_at": self.created_at,
            "command_plan": dict(self.command_plan),
            "policy_verdict": dict(self.policy_verdict),
            "projection_journal": dict(self.projection_journal),
            "projection_observations": dict(self.projection_observations),
            "consistency_report": dict(self.consistency_report),
            "outcome": dict(self.outcome),
            "summary": dict(self.summary),
        }


def _summary(command_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    command_plan = _as_dict(payload.get("command_plan"))
    policy_verdict = _as_dict(payload.get("policy_verdict"))
    projection_journal = _as_dict(payload.get("projection_journal"))
    projection_observations = _as_dict(payload.get("projection_observations"))
    consistency_report = _as_dict(payload.get("consistency_report"))
    outcome = _as_dict(payload.get("outcome"))
    journal_entries = _as_list(projection_journal.get("entries"))
    observations = _as_list(projection_observations.get("observations"))
    return {
        "module": str(payload.get("module", "")),
        "operation": str(payload.get("operation", "")),
        "command_id": command_id,
        "command_kind": str(command_plan.get("command_kind", "")),
        "policy_allowed": bool(policy_verdict.get("allowed", True)),
        "policy_effective_allowed": bool(
            policy_verdict.get("effective_allowed", policy_verdict.get("allowed", True))
        ),
        "missing_permissions": list(_as_list(policy_verdict.get("missing_permissions"))),
        "protected_surfaces": list(_as_list(policy_verdict.get("protected_surfaces"))),
        "consistency_ok": bool(consistency_report.get("ok", True)),
        "projection_count": len(journal_entries),
        "observation_count": len(observations),
        "projection_surfaces": sorted(_surfaces(journal_entries)),
        "outcome_ok": bool(outcome.get("ok", True)),
    }


def _extract_command_id(payload: dict[str, Any]) -> str:
    command_plan = _as_dict(payload.get("command_plan"))
    policy_verdict = _as_dict(payload.get("policy_verdict"))
    policy_contract = _as_dict(policy_verdict.get("contract"))
    projection_journal = _as_dict(payload.get("projection_journal"))
    projection_observations = _as_dict(payload.get("projection_observations"))
    consistency_report = _as_dict(payload.get("consistency_report"))
    for candidate in (
        command_plan.get("command_id"),
        policy_contract.get("command_id"),
        projection_journal.get("command_id"),
        projection_observations.get("command_id"),
        consistency_report.get("command_id"),
    ):
        if candidate:
            return str(candidate)
    return "cmd_unknown"


def _created_at(payload: dict[str, Any]) -> str:
    projection_journal = _as_dict(payload.get("projection_journal"))
    return str(projection_journal.get("created_at") or "1970-01-01T00:00:00+00:00")


def _stable_id(command_id: str, payload: dict[str, Any]) -> str:
    identity = {"command_id": str(command_id), **_json_safe(payload)}
    serialized = json.dumps(identity, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return f"dec_{hashlib.sha256(serialized.encode('utf-8')).hexdigest()[:32]}"


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


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False, default=str))
