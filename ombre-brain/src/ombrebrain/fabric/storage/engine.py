from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ombrebrain.fabric.log.wal import WalStore
from ombrebrain.protocol.schemas import MemoryEvent, MemoryType


@dataclass(frozen=True)
class MemoryFabric:
    wal: WalStore

    @classmethod
    def open(cls, root: str | Path) -> "MemoryFabric":
        return cls(WalStore(Path(root) / "fabric" / "memory.wal"))

    def append_event(self, event: MemoryEvent) -> int:
        return self.wal.append(event.to_dict()).index

    def next_index(self) -> int:
        return self.wal.next_index()

    def replay_events(self) -> list[MemoryEvent]:
        return [MemoryEvent.from_dict(entry.payload) for entry in self.wal.replay()]

    def events_by_type(self, memory_type: MemoryType) -> list[MemoryEvent]:
        expected_type = MemoryType(memory_type)
        return [event for event in self.replay_events() if event.memory_type == expected_type]

    def purge_legacy_bucket(self, bucket_id: str) -> int:
        """Remove persisted v3 events copied from one legacy bucket."""
        expected = str(bucket_id)

        def belongs_to_bucket(payload: dict[str, object]) -> bool:
            metadata = payload.get("metadata")
            return (
                isinstance(metadata, dict)
                and str(metadata.get("legacy_bucket_id") or "") == expected
            )

        return self.wal.rewrite_excluding(belongs_to_bucket)
