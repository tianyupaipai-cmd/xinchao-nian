from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ombrebrain.domain.commands import ProjectionKind
from ombrebrain.projection.journal import ProjectionJournal, ProjectionJournalEntry
from ombrebrain.projection.observation import ObservationStatus, ProjectionObservation, ProjectionObservationSet


@dataclass(frozen=True)
class BucketProjectionObserver:
    bucket_manager: Any = None

    async def observe(self, entry: ProjectionJournalEntry) -> ProjectionObservation:
        bucket_id = _subject_from_entry(entry)
        if not bucket_id or self.bucket_manager is None or not hasattr(self.bucket_manager, "get"):
            return _unknown(entry, bucket_id, reason="bucket manager or bucket id unavailable")
        try:
            bucket = await self.bucket_manager.get(bucket_id)
        except Exception as exc:
            return _failed(entry, bucket_id, exc)
        if bucket is None:
            return ProjectionObservation(
                projection_kind=entry.projection_kind,
                surface=entry.surface,
                action=entry.action,
                status=ObservationStatus.MISSING,
                subject=bucket_id,
                metadata={"exists": False},
            )
        return ProjectionObservation(
            projection_kind=entry.projection_kind,
            surface=entry.surface,
            action=entry.action,
            status=ObservationStatus.OBSERVED,
            subject=bucket_id,
            metadata={
                "exists": True,
                "bucket_type": str((bucket.get("metadata") or {}).get("type", "")) if isinstance(bucket, dict) else "",
            },
        )


@dataclass(frozen=True)
class VectorProjectionObserver:
    embedding_engine: Any = None

    async def observe(self, entry: ProjectionJournalEntry) -> ProjectionObservation:
        bucket_id = _subject_from_entry(entry)
        if not bucket_id or self.embedding_engine is None:
            return _unknown(entry, bucket_id, reason="embedding engine or bucket id unavailable")
        if not bool(getattr(self.embedding_engine, "enabled", True)):
            return _unknown(entry, bucket_id, reason="embedding engine disabled")
        try:
            if hasattr(self.embedding_engine, "get_embedding"):
                embedding = await self.embedding_engine.get_embedding(bucket_id)
                exists = bool(embedding)
            elif hasattr(self.embedding_engine, "list_all_ids"):
                ids = self.embedding_engine.list_all_ids()
                exists = bucket_id in set(ids or ())
            else:
                return _unknown(entry, bucket_id, reason="embedding read interface unavailable")
        except Exception as exc:
            return _failed(entry, bucket_id, exc)
        return ProjectionObservation(
            projection_kind=entry.projection_kind,
            surface=entry.surface,
            action=entry.action,
            status=ObservationStatus.OBSERVED if exists else ObservationStatus.MISSING,
            subject=bucket_id,
            metadata={"exists": exists},
        )


@dataclass(frozen=True)
class DashboardProjectionObserver:
    config_snapshot: dict[str, Any] | None = None

    async def observe(self, entry: ProjectionJournalEntry) -> ProjectionObservation:
        config = self.config_snapshot or {}
        if not config:
            return _unknown(entry, "", reason="config snapshot unavailable")
        known = any(key in config for key in ("buckets_dir", "transport", "host_port", "mcp_require_auth"))
        return ProjectionObservation(
            projection_kind=entry.projection_kind,
            surface=entry.surface,
            action=entry.action,
            status=ObservationStatus.OBSERVED if known else ObservationStatus.UNKNOWN,
            metadata={"has_config_snapshot": True, "known_dashboard_keys": known},
        )


@dataclass(frozen=True)
class DeploymentProjectionObserver:
    config_snapshot: dict[str, Any] | None = None

    async def observe(self, entry: ProjectionJournalEntry) -> ProjectionObservation:
        config = self.config_snapshot or {}
        if not config:
            return _unknown(entry, "", reason="deployment snapshot unavailable")
        return ProjectionObservation(
            projection_kind=entry.projection_kind,
            surface=entry.surface,
            action=entry.action,
            status=ObservationStatus.OBSERVED,
            metadata={
                "has_buckets_dir": bool(config.get("buckets_dir")),
                "has_transport": bool(config.get("transport")),
            },
        )


@dataclass(frozen=True)
class ProjectionObserverRegistry:
    bucket_observer: BucketProjectionObserver
    vector_observer: VectorProjectionObserver
    dashboard_observer: DashboardProjectionObserver
    deployment_observer: DeploymentProjectionObserver

    @classmethod
    def default(
        cls,
        *,
        bucket_manager: Any = None,
        embedding_engine: Any = None,
        config_snapshot: dict[str, Any] | None = None,
    ) -> "ProjectionObserverRegistry":
        return cls(
            bucket_observer=BucketProjectionObserver(bucket_manager),
            vector_observer=VectorProjectionObserver(embedding_engine),
            dashboard_observer=DashboardProjectionObserver(config_snapshot),
            deployment_observer=DeploymentProjectionObserver(config_snapshot),
        )

    async def observe(self, _plan, journal: ProjectionJournal) -> ProjectionObservationSet:
        observations = []
        for entry in journal.entries:
            observations.append(await self._observe_entry(entry))
        return ProjectionObservationSet(command_id=journal.command_id, observations=tuple(observations), created_at=journal.created_at)

    async def _observe_entry(self, entry: ProjectionJournalEntry) -> ProjectionObservation:
        if entry.projection_kind == ProjectionKind.BUCKET_MARKDOWN:
            return await self.bucket_observer.observe(entry)
        if entry.projection_kind == ProjectionKind.VECTOR_INDEX:
            return await self.vector_observer.observe(entry)
        if entry.projection_kind == ProjectionKind.DASHBOARD_STATE:
            return await self.dashboard_observer.observe(entry)
        if entry.projection_kind == ProjectionKind.DEPLOYMENT_STATE:
            return await self.deployment_observer.observe(entry)
        return _unknown(entry, _subject_from_entry(entry), reason="projection kind has no real observer")


def _subject_from_entry(entry: ProjectionJournalEntry) -> str:
    metadata = dict(entry.metadata or {})
    payload = metadata.get("payload")
    if isinstance(payload, dict):
        for key in ("bucket_id", "id", "bucket"):
            value = payload.get(key)
            if value:
                return str(value)
    for key in ("bucket_id", "id", "subject"):
        value = metadata.get(key)
        if value:
            return str(value)
    return ""


def _unknown(entry: ProjectionJournalEntry, subject: str, *, reason: str) -> ProjectionObservation:
    return ProjectionObservation(
        projection_kind=entry.projection_kind,
        surface=entry.surface,
        action=entry.action,
        status=ObservationStatus.UNKNOWN,
        subject=subject,
        metadata={"reason": reason},
    )


def _failed(entry: ProjectionJournalEntry, subject: str, exc: Exception) -> ProjectionObservation:
    return ProjectionObservation(
        projection_kind=entry.projection_kind,
        surface=entry.surface,
        action=entry.action,
        status=ObservationStatus.FAILED,
        subject=subject,
        metadata={"error_type": type(exc).__name__, "error_message": str(exc)[:240]},
    )
