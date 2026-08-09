from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import json
from typing import Any

from ombrebrain.domain.commands import ProjectionKind


class ObservationStatus(Enum):
    OBSERVED = "observed"
    MISSING = "missing"
    UNKNOWN = "unknown"
    FAILED = "failed"


@dataclass(frozen=True)
class ProjectionObservation:
    projection_kind: ProjectionKind
    surface: str
    action: str
    status: ObservationStatus
    subject: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "projection_kind", _coerce_projection_kind(self.projection_kind))
        object.__setattr__(self, "surface", str(self.surface))
        object.__setattr__(self, "action", str(self.action))
        object.__setattr__(self, "status", _coerce_status(self.status))
        object.__setattr__(self, "subject", str(self.subject or ""))
        object.__setattr__(self, "metadata", _json_safe(self.metadata))

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.projection_kind.value, self.surface, self.action)

    def to_dict(self) -> dict[str, Any]:
        return {
            "projection_kind": self.projection_kind.value,
            "surface": self.surface,
            "action": self.action,
            "status": self.status.value,
            "subject": self.subject,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ProjectionObservationSet:
    command_id: str
    observations: tuple[ProjectionObservation, ...]
    created_at: str = "1970-01-01T00:00:00+00:00"

    def __post_init__(self) -> None:
        object.__setattr__(self, "command_id", str(self.command_id))
        object.__setattr__(self, "observations", tuple(self.observations))
        object.__setattr__(self, "created_at", str(self.created_at))

    def to_dict(self) -> dict[str, Any]:
        return {
            "command_id": self.command_id,
            "created_at": self.created_at,
            "observations": [obs.to_dict() for obs in self.observations],
        }


def _coerce_projection_kind(value: object) -> ProjectionKind:
    if isinstance(value, ProjectionKind):
        return value
    return ProjectionKind(str(value))


def _coerce_status(value: object) -> ObservationStatus:
    if isinstance(value, ObservationStatus):
        return value
    return ObservationStatus(str(value))


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False, default=str))
