from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from ombrebrain.protocol.schemas import MemoryEvent


@dataclass(frozen=True)
class RaftLogEntry:
    term: int
    index: int
    event: MemoryEvent
    checksum: str

    @classmethod
    def new(cls, *, term: int, index: int, event: MemoryEvent) -> "RaftLogEntry":
        return cls(term=term, index=index, event=event, checksum=_entry_checksum(term, index, event))

    def verify(self) -> bool:
        return self.checksum == _entry_checksum(self.term, self.index, self.event)


def _entry_checksum(term: int, index: int, event: MemoryEvent) -> str:
    payload = json.dumps(
        event.to_dict(),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(f"{term}|{index}|{payload}".encode("utf-8")).hexdigest()
