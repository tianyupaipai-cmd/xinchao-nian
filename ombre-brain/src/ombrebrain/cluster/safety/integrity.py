from __future__ import annotations

from ombrebrain.fabric.log.snapshot import MemorySnapshot, _snapshot_checksum, _validate_snapshot_shape
from ombrebrain.kernel.errors import LogIntegrityError
from ombrebrain.protocol.schemas import MemoryEvent


def verify_snapshot(snapshot: MemorySnapshot) -> bool:
    for event in snapshot.events:
        MemoryEvent.from_dict(event.to_dict())

    _validate_snapshot_shape(snapshot)
    expected_checksum = _snapshot_checksum(snapshot.last_index, snapshot.last_term, snapshot.events)
    if snapshot.checksum != expected_checksum:
        raise LogIntegrityError("Snapshot checksum mismatch")

    return True
