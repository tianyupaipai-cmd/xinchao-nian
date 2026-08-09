from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ombrebrain.domain.commands import CommandPlan
from ombrebrain.projection.journal import ProjectionJournal, ProjectionJournalEntry


@dataclass(frozen=True)
class ProjectionRuntime:
    created_at: str = "1970-01-01T00:00:00+00:00"

    @classmethod
    def default(cls) -> "ProjectionRuntime":
        return cls()

    def project(
        self,
        plan: CommandPlan,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> ProjectionJournal:
        base_metadata = dict(metadata or {})
        entries = tuple(
            ProjectionJournalEntry.planned(
                command_id=plan.command_id,
                command_kind=plan.command_kind,
                step=step,
                metadata={
                    **base_metadata,
                    "step_index": index,
                    "policy_tags": list(plan.policy_tags),
                },
            )
            for index, step in enumerate(plan.projections)
        )
        return ProjectionJournal(command_id=plan.command_id, entries=entries, created_at=self.created_at)
