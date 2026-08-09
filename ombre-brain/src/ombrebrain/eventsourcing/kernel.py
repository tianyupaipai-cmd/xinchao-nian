from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from ombrebrain.domain.commands import CommandPlan
from ombrebrain.eventsourcing.contracts import EventProjectionMutation, EventSourcedEnvelope
from ombrebrain.protocol.schemas import ActorKind, MemoryEvent, MemoryType, Visibility


@dataclass(frozen=True)
class EventSourcedMemoryKernel:
    mode: str = "command_event_projection"

    @classmethod
    def default(cls) -> "EventSourcedMemoryKernel":
        return cls()

    def prepare(
        self,
        *,
        module: str,
        operation: str,
        command_plan: CommandPlan,
        legacy_metadata: dict[str, Any],
    ) -> EventSourcedEnvelope:
        projection_batch = tuple(
            EventProjectionMutation(
                kind=step.kind.value,
                action=step.action,
                surface=step.surface,
            )
            for step in command_plan.projections
        )
        metadata = {
            "event_sourced": {
                "mode": self.mode,
                "module": str(module),
                "operation": str(operation),
                "command_id": command_plan.command_id,
                "command_kind": command_plan.command_kind.value,
                "writes_memory": command_plan.writes_memory,
                "legacy_metadata": _json_safe(legacy_metadata),
            }
        }
        event = MemoryEvent.new(
            actor=ActorKind.SYSTEM,
            actor_name="event-sourced-kernel",
            memory_type=MemoryType.TRACE,
            content=f"event-sourced command: {module}.{operation}",
            visibility=Visibility.INTERNAL,
            source_chain=("event_sourced_kernel", str(module), str(operation)),
            metadata=metadata,
        )
        return EventSourcedEnvelope(event=event, projection_batch=projection_batch)


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False, default=str))
