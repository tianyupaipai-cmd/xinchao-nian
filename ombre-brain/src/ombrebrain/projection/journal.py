from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
from typing import Any

from ombrebrain.domain.commands import CommandKind, ProjectionKind, ProjectionStep


class ProjectionStatus(Enum):
    PLANNED = "planned"
    OBSERVED = "observed"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True)
class ProjectionJournalEntry:
    command_id: str
    command_kind: CommandKind
    projection_kind: ProjectionKind
    surface: str
    action: str
    status: ProjectionStatus = ProjectionStatus.PLANNED
    checksum: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "command_id", str(self.command_id))
        object.__setattr__(self, "command_kind", _coerce_enum(CommandKind, self.command_kind))
        object.__setattr__(self, "projection_kind", _coerce_enum(ProjectionKind, self.projection_kind))
        object.__setattr__(self, "surface", str(self.surface))
        object.__setattr__(self, "action", str(self.action))
        object.__setattr__(self, "status", _coerce_enum(ProjectionStatus, self.status))
        object.__setattr__(self, "metadata", _json_safe(self.metadata))
        if not self.checksum:
            object.__setattr__(self, "checksum", _checksum(self._checksum_payload()))
        else:
            object.__setattr__(self, "checksum", str(self.checksum))

    @classmethod
    def planned(
        cls,
        *,
        command_id: str,
        command_kind: CommandKind,
        step: ProjectionStep,
        metadata: Mapping[str, Any] | None = None,
    ) -> "ProjectionJournalEntry":
        return cls(
            command_id=command_id,
            command_kind=command_kind,
            projection_kind=step.kind,
            surface=step.surface,
            action=step.action,
            status=ProjectionStatus.PLANNED,
            metadata=dict(metadata or {}),
        )

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.projection_kind.value, self.surface, self.action)

    def to_dict(self) -> dict[str, Any]:
        return {
            "command_id": self.command_id,
            "command_kind": self.command_kind.value,
            "projection_kind": self.projection_kind.value,
            "surface": self.surface,
            "action": self.action,
            "status": self.status.value,
            "checksum": self.checksum,
            "metadata": dict(self.metadata),
        }

    def _checksum_payload(self) -> dict[str, Any]:
        return {
            "command_id": self.command_id,
            "command_kind": self.command_kind.value,
            "projection_kind": self.projection_kind.value,
            "surface": self.surface,
            "action": self.action,
            "status": self.status.value,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class ProjectionJournal:
    command_id: str
    entries: tuple[ProjectionJournalEntry, ...]
    created_at: str = "1970-01-01T00:00:00+00:00"

    def __post_init__(self) -> None:
        object.__setattr__(self, "command_id", str(self.command_id))
        object.__setattr__(self, "entries", tuple(self.entries))
        object.__setattr__(self, "created_at", str(self.created_at))

    def to_dict(self) -> dict[str, Any]:
        return {
            "command_id": self.command_id,
            "created_at": self.created_at,
            "entries": [entry.to_dict() for entry in self.entries],
        }


def _coerce_enum(enum_type: type[Enum], value: object) -> Enum:
    if isinstance(value, enum_type):
        return value
    return enum_type(str(value))


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False, default=str))


def _checksum(payload: Mapping[str, Any]) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return f"proj_{hashlib.sha256(serialized.encode('utf-8')).hexdigest()[:32]}"
