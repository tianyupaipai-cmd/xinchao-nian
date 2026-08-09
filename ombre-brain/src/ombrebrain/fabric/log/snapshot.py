from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Iterable

from ombrebrain.kernel.errors import LogIntegrityError
from ombrebrain.protocol.schemas import MemoryEvent


@dataclass(frozen=True)
class MemorySnapshot:
    last_index: int
    last_term: int
    events: tuple[MemoryEvent, ...]
    checksum: str

    @classmethod
    def from_events(cls, events: Iterable[MemoryEvent]) -> "MemorySnapshot":
        normalized = tuple(events)
        last_event = max(normalized, key=lambda event: event.cluster_index, default=None)
        last_index = 0 if last_event is None else last_event.cluster_index
        last_term = 0 if last_event is None else last_event.cluster_term
        checksum = _snapshot_checksum(last_index, last_term, normalized)
        return cls(last_index=last_index, last_term=last_term, events=normalized, checksum=checksum)

    def to_dict(self) -> dict[str, object]:
        return {
            "last_index": self.last_index,
            "last_term": self.last_term,
            "events": [event.to_dict() for event in self.events],
            "checksum": self.checksum,
        }

    def save(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: str | Path) -> "MemorySnapshot":
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise LogIntegrityError("Invalid snapshot JSON") from exc
        if not isinstance(payload, dict):
            raise LogIntegrityError("Invalid snapshot payload")

        try:
            events = tuple(MemoryEvent.from_dict(item) for item in payload["events"])
            snapshot = cls(
                last_index=int(payload["last_index"]),
                last_term=int(payload["last_term"]),
                events=events,
                checksum=str(payload["checksum"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise LogIntegrityError("Invalid snapshot fields") from exc

        _validate_snapshot_shape(snapshot)
        if snapshot.checksum != _snapshot_checksum(snapshot.last_index, snapshot.last_term, snapshot.events):
            raise LogIntegrityError("Snapshot checksum mismatch")
        return snapshot


def _snapshot_checksum(last_index: int, last_term: int, events: tuple[MemoryEvent, ...]) -> str:
    payload = {
        "last_index": int(last_index),
        "last_term": int(last_term),
        "events": [event.to_dict() for event in events],
    }
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _validate_snapshot_shape(snapshot: MemorySnapshot) -> None:
    indexes = [event.cluster_index for event in snapshot.events]
    if not indexes:
        if snapshot.last_index != 0 or snapshot.last_term != 0:
            raise LogIntegrityError("Snapshot indexes must be contiguous")
        return

    expected_indexes = list(range(1, snapshot.last_index + 1))
    if sorted(indexes) != expected_indexes:
        raise LogIntegrityError("Snapshot indexes must be contiguous")

    final_events = [event for event in snapshot.events if event.cluster_index == snapshot.last_index]
    if len(final_events) != 1 or final_events[0].cluster_term != snapshot.last_term:
        raise LogIntegrityError("Snapshot last_term does not match last_index event")
