from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from ombrebrain.cluster.raft.log import RaftLogEntry
from ombrebrain.cluster.safety.integrity import verify_snapshot
from ombrebrain.fabric.log.snapshot import MemorySnapshot
from ombrebrain.fabric.storage.engine import MemoryFabric
from ombrebrain.kernel.errors import LogIntegrityError, SnapshotRestoreError


@dataclass(frozen=True)
class CatchUpResult:
    installed_snapshot: bool
    appended_entries: int
    last_index: int


def catch_up_follower(
    fabric: MemoryFabric,
    *,
    current_index: int,
    entries: Iterable[RaftLogEntry],
    snapshot: MemorySnapshot | None = None,
) -> CatchUpResult:
    index = int(current_index)
    appended = 0
    installed_snapshot = False

    if snapshot is not None and index < snapshot.last_index:
        verify_snapshot(snapshot)
        for event in sorted(snapshot.events, key=lambda item: item.cluster_index):
            if event.cluster_index > index:
                fabric.append_event(event)
                appended += 1
        index = snapshot.last_index
        installed_snapshot = True

    for entry in sorted(entries, key=lambda item: item.index):
        if not entry.verify():
            raise LogIntegrityError("Raft log entry checksum mismatch")
        if entry.index <= index:
            continue
        if entry.index != index + 1:
            raise SnapshotRestoreError(
                f"Cannot catch up follower: expected log index {index + 1}, got {entry.index}"
            )
        fabric.append_event(entry.event)
        index = entry.index
        appended += 1

    return CatchUpResult(installed_snapshot=installed_snapshot, appended_entries=appended, last_index=index)
