from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from ombrebrain.protocol.schemas import MemoryEvent


class CollaborationGraph:
    def __init__(self, events: Iterable[MemoryEvent] = ()) -> None:
        self._events: dict[str, MemoryEvent] = {}
        self._children: dict[str, list[MemoryEvent]] = defaultdict(list)

        for event in events:
            self.add(event)

    def add(self, event: MemoryEvent) -> None:
        if event.id in self._events:
            raise ValueError(f"Duplicate memory event id: {event.id}")

        self._events[event.id] = event
        for parent_id in event.parent_event_ids:
            self._children[parent_id].append(event)

    def get(self, event_id: str) -> MemoryEvent:
        try:
            return self._events[event_id]
        except KeyError as exc:
            raise KeyError(f"Unknown memory event id: {event_id}") from exc

    def parents(self, event_id: str) -> tuple[MemoryEvent, ...]:
        event = self.get(event_id)
        return tuple(self._events[parent_id] for parent_id in event.parent_event_ids if parent_id in self._events)

    def children(self, event_id: str) -> tuple[MemoryEvent, ...]:
        self.get(event_id)
        return tuple(self._children.get(event_id, ()))

    def events_for_actor(self, actor_name: str) -> tuple[MemoryEvent, ...]:
        return tuple(event for event in self._events.values() if event.actor_name == actor_name)

    def source_chain(self, event_id: str) -> tuple[str, ...]:
        seen: set[str] = set()
        chain: list[str] = []

        def visit(current_id: str) -> None:
            if current_id in seen:
                return
            seen.add(current_id)
            event = self.get(current_id)
            for parent_id in event.parent_event_ids:
                if parent_id in self._events:
                    visit(parent_id)
            for source in event.source_chain:
                if source not in chain:
                    chain.append(source)

        visit(event_id)
        return tuple(chain)
