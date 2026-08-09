from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ombrebrain.decision.records import DecisionRecord


@dataclass(frozen=True)
class DecisionLedger:
    @classmethod
    def default(cls) -> "DecisionLedger":
        return cls()

    def record(
        self,
        *,
        module: str,
        operation: str,
        command_plan: dict[str, Any],
        policy_metadata: dict[str, Any],
        projection_metadata: dict[str, Any],
        outcome: dict[str, Any],
    ) -> DecisionRecord:
        return DecisionRecord.new(
            module=module,
            operation=operation,
            command_plan=_as_dict(command_plan),
            policy_verdict=_as_dict(policy_metadata.get("policy_verdict")),
            projection_journal=_as_dict(projection_metadata.get("projection_journal")),
            projection_observations=_as_dict(projection_metadata.get("projection_observations")),
            consistency_report=_as_dict(projection_metadata.get("consistency_report")),
            outcome=_as_dict(outcome),
        )


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
