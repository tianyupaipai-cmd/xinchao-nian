from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from ombrebrain.domain.commands import CommandPlan
from ombrebrain.projection.auditor import ConsistencyAuditor
from ombrebrain.projection.journal import ProjectionJournal
from ombrebrain.projection.observation import ObservationStatus, ProjectionObservation, ProjectionObservationSet
from ombrebrain.projection.observers import ProjectionObserverRegistry
from ombrebrain.projection.runtime import ProjectionRuntime


@dataclass(frozen=True)
class ProjectionAuditRuntime:
    projection_runtime: ProjectionRuntime
    consistency_auditor: ConsistencyAuditor
    observer_registry: ProjectionObserverRegistry

    @classmethod
    def default(
        cls,
        *,
        bucket_manager: Any = None,
        embedding_engine: Any = None,
        config_snapshot: dict[str, Any] | None = None,
    ) -> "ProjectionAuditRuntime":
        return cls(
            projection_runtime=ProjectionRuntime.default(),
            consistency_auditor=ConsistencyAuditor.default(),
            observer_registry=ProjectionObserverRegistry.default(
                bucket_manager=bucket_manager,
                embedding_engine=embedding_engine,
                config_snapshot=config_snapshot,
            ),
        )

    def audit(self, command_plan: CommandPlan, legacy_metadata: dict[str, object]) -> dict[str, object]:
        journal = self.projection_runtime.project(command_plan, metadata={"payload": legacy_metadata})
        observations = self._observe_best_effort(command_plan, journal)
        report = self.consistency_auditor.audit_with_observations(
            command_plan,
            journal,
            observations,
            legacy_metadata,
        )
        return {
            "projection_journal": journal.to_dict(),
            "projection_observations": observations.to_dict(),
            "consistency_report": report.to_dict(),
        }

    def _observe_best_effort(self, command_plan: CommandPlan, journal: ProjectionJournal) -> ProjectionObservationSet:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            try:
                return asyncio.run(self.observer_registry.observe(command_plan, journal))
            except Exception as exc:
                return _unknown_observations(journal, f"observer registry failed: {type(exc).__name__}: {str(exc)[:160]}")
        return _unknown_observations(journal, "observation skipped inside running event loop")


def _unknown_observations(journal: ProjectionJournal, reason: str) -> ProjectionObservationSet:
    return ProjectionObservationSet(
        command_id=journal.command_id,
        observations=tuple(
            ProjectionObservation(
                projection_kind=entry.projection_kind,
                surface=entry.surface,
                action=entry.action,
                status=ObservationStatus.UNKNOWN,
                subject=str((entry.metadata.get("payload") or {}).get("bucket_id", "")) if isinstance(entry.metadata.get("payload"), dict) else "",
                metadata={"reason": reason},
            )
            for entry in journal.entries
        ),
        created_at=journal.created_at,
    )
