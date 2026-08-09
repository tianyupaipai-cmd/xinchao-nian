from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from ombrebrain.protocol.schemas import MemoryEvent


@dataclass(frozen=True)
class EventProjectionMutation:
    kind: str
    action: str
    surface: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", str(self.kind))
        object.__setattr__(self, "action", str(self.action))
        object.__setattr__(self, "surface", str(self.surface))

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "action": self.action, "surface": self.surface}


@dataclass(frozen=True)
class EventSourcedEnvelope:
    event: MemoryEvent
    projection_batch: tuple[EventProjectionMutation, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "projection_batch", tuple(self.projection_batch))

    @property
    def command_id(self) -> str:
        return str(self.event.metadata.get("event_sourced", {}).get("command_id", ""))

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(
            {
                "event": self.event.to_dict(),
                "projection_batch": [mutation.to_dict() for mutation in self.projection_batch],
            }
        )

    def summary(self) -> dict[str, Any]:
        metadata = dict(self.event.metadata.get("event_sourced", {}))
        return _json_safe(
            {
                **metadata,
                "event_id": self.event.id,
                "projection_count": len(self.projection_batch),
                "projection_surfaces": [mutation.surface for mutation in self.projection_batch],
            }
        )


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False, default=str))
