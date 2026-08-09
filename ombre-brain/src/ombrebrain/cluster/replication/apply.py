from __future__ import annotations

from ombrebrain.fabric.storage.engine import MemoryFabric
from ombrebrain.protocol.schemas import MemoryEvent


def apply_committed_event(fabric: MemoryFabric, event: MemoryEvent) -> int:
    return fabric.append_event(event)
