from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
import json
from typing import Any

from ombrebrain.domain.commands import CommandPlan
from ombrebrain.projection.journal import ProjectionJournal, ProjectionStatus
from ombrebrain.projection.observation import ObservationStatus, ProjectionObservationSet


ProjectionKey = tuple[str, str, str]


@dataclass(frozen=True)
class ConsistencyIssue:
    code: str
    message: str
    key: ProjectionKey | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", str(self.code))
        object.__setattr__(self, "message", str(self.message))
        object.__setattr__(self, "metadata", _json_safe(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "key": list(self.key) if self.key is not None else None,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ConsistencyReport:
    command_id: str
    ok: bool
    expected_count: int
    observed_count: int
    issues: tuple[ConsistencyIssue, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "command_id", str(self.command_id))
        object.__setattr__(self, "expected_count", int(self.expected_count))
        object.__setattr__(self, "observed_count", int(self.observed_count))
        object.__setattr__(self, "issues", tuple(self.issues))
        object.__setattr__(self, "metadata", _json_safe(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "command_id": self.command_id,
            "ok": self.ok,
            "expected_count": self.expected_count,
            "observed_count": self.observed_count,
            "issues": [issue.to_dict() for issue in self.issues],
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ConsistencyAuditor:
    @classmethod
    def default(cls) -> "ConsistencyAuditor":
        return cls()

    def audit(
        self,
        plan: CommandPlan,
        journal: ProjectionJournal,
        legacy_metadata: Mapping[str, Any] | None = None,
    ) -> ConsistencyReport:
        expected_keys = tuple((step.kind.value, step.surface, step.action) for step in plan.projections)
        observed_keys = tuple(entry.key for entry in journal.entries)
        expected_counts = Counter(expected_keys)
        observed_counts = Counter(observed_keys)
        issues: list[ConsistencyIssue] = []

        if plan.command_id != journal.command_id:
            issues.append(
                ConsistencyIssue(
                    code="command_id_mismatch",
                    message="journal command id does not match command plan",
                    metadata={"expected": plan.command_id, "observed": journal.command_id},
                )
            )

        for key, expected_count in expected_counts.items():
            observed_count = observed_counts.get(key, 0)
            if observed_count == 0:
                issues.append(
                    ConsistencyIssue(
                        code="missing_projection",
                        message="planned projection is missing from journal",
                        key=key,
                        metadata={"expected": expected_count, "observed": observed_count},
                    )
                )
            elif observed_count > expected_count:
                issues.append(
                    ConsistencyIssue(
                        code="duplicate_projection",
                        message="projection appears more times than planned",
                        key=key,
                        metadata={"expected": expected_count, "observed": observed_count},
                    )
                )

        for key, observed_count in observed_counts.items():
            if key not in expected_counts:
                issues.append(
                    ConsistencyIssue(
                        code="unexpected_projection",
                        message="journal contains a projection not present in the command plan",
                        key=key,
                        metadata={"observed": observed_count},
                    )
                )

        for entry in journal.entries:
            if entry.command_id != journal.command_id:
                issues.append(
                    ConsistencyIssue(
                        code="entry_command_id_mismatch",
                        message="journal entry command id does not match journal command id",
                        key=entry.key,
                        metadata={"journal": journal.command_id, "entry": entry.command_id},
                    )
                )
            if entry.status not in (ProjectionStatus.PLANNED, ProjectionStatus.OBSERVED):
                issues.append(
                    ConsistencyIssue(
                        code="projection_not_planned",
                        message="projection entry is skipped or failed",
                        key=entry.key,
                        metadata={"status": entry.status.value},
                    )
                )

        return ConsistencyReport(
            command_id=plan.command_id,
            ok=not issues,
            expected_count=len(expected_keys),
            observed_count=len(observed_keys),
            issues=tuple(issues),
            metadata={
                "legacy_metadata": _json_safe(dict(legacy_metadata or {})),
            },
        )

    def audit_with_observations(
        self,
        plan: CommandPlan,
        journal: ProjectionJournal,
        observations: ProjectionObservationSet,
        legacy_metadata: Mapping[str, Any] | None = None,
    ) -> ConsistencyReport:
        base = self.audit(plan, journal, legacy_metadata)
        expected_keys = tuple((step.kind.value, step.surface, step.action) for step in plan.projections)
        expected_counts = Counter(expected_keys)
        observation_keys = tuple(obs.key for obs in observations.observations)
        observation_counts = Counter(observation_keys)
        issues = list(base.issues)
        unknown_count = 0

        if observations.command_id != plan.command_id:
            issues.append(
                ConsistencyIssue(
                    code="observation_command_id_mismatch",
                    message="observation set command id does not match command plan",
                    metadata={"expected": plan.command_id, "observed": observations.command_id},
                )
            )

        for key, expected_count in expected_counts.items():
            observed_count = observation_counts.get(key, 0)
            if observed_count == 0:
                issues.append(
                    ConsistencyIssue(
                        code="missing_observation",
                        message="planned projection has no real-state observation",
                        key=key,
                        metadata={"expected": expected_count, "observed": observed_count},
                    )
                )

        for key, observed_count in observation_counts.items():
            if key not in expected_counts:
                issues.append(
                    ConsistencyIssue(
                        code="unexpected_observation",
                        message="observer reported a projection not present in the command plan",
                        key=key,
                        metadata={"observed": observed_count},
                    )
                )

        for obs in observations.observations:
            if obs.status == ObservationStatus.UNKNOWN:
                unknown_count += 1
            elif obs.status == ObservationStatus.MISSING:
                issues.append(
                    ConsistencyIssue(
                        code="observer_missing_projection",
                        message="observer could not find expected real projection state",
                        key=obs.key,
                        metadata={"subject": obs.subject},
                    )
                )
            elif obs.status == ObservationStatus.FAILED:
                issues.append(
                    ConsistencyIssue(
                        code="observer_failed",
                        message="observer failed while reading real projection state",
                        key=obs.key,
                        metadata={"subject": obs.subject, **dict(obs.metadata)},
                    )
                )

        return ConsistencyReport(
            command_id=plan.command_id,
            ok=not issues,
            expected_count=base.expected_count,
            observed_count=base.observed_count,
            issues=tuple(issues),
            metadata={
                **dict(base.metadata),
                "observation_count": len(observations.observations),
                "unknown_observations": unknown_count,
            },
        )


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False, default=str))
