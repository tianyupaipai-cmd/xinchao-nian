from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import threading
from typing import Callable, Iterator

from ombrebrain.kernel.errors import LogIntegrityError


_PATH_LOCKS: dict[str, threading.RLock] = {}
_PATH_LOCKS_GUARD = threading.Lock()


def _path_lock(path: Path) -> threading.RLock:
    key = str(path.expanduser().resolve(strict=False))
    with _PATH_LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(key, threading.RLock())


@contextmanager
def _exclusive_file_lock(path: Path) -> Iterator[None]:
    """Serialize writers across processes using a sidecar lock file."""
    lock_path = path.with_name(f"{path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        if os.name == "nt":
            import msvcrt

            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@dataclass(frozen=True)
class WalEntry:
    index: int
    previous_checksum: str
    checksum: str
    payload: dict[str, object]


class WalStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._process_lock = _path_lock(self.path)

    @contextmanager
    def _locked(self) -> Iterator[None]:
        with self._process_lock:
            with _exclusive_file_lock(self.path):
                yield

    def append(self, payload: dict[str, object]) -> WalEntry:
        with self._locked():
            last_entry = self._last_entry_unlocked()
            index = 1 if last_entry is None else last_entry.index + 1
            previous_checksum = "" if last_entry is None else last_entry.checksum
            checksum = _entry_checksum(index, previous_checksum, payload)
            entry = WalEntry(
                index=index,
                previous_checksum=previous_checksum,
                checksum=checksum,
                payload=dict(payload),
            )
            record = {
                "index": entry.index,
                "previous_checksum": entry.previous_checksum,
                "checksum": entry.checksum,
                "payload": entry.payload,
            }

            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
                handle.write("\n")
                handle.flush()
            return entry

    def replay(self) -> Iterator[WalEntry]:
        with self._locked():
            yield from self._replay_unlocked()

    def _replay_unlocked(self) -> Iterator[WalEntry]:
        if not self.path.exists():
            return

        expected_index = 1
        previous_checksum = ""
        with self.path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                record = _load_record(stripped, line_number)
                entry = _entry_from_record(record, line_number)

                if entry.index != expected_index:
                    raise LogIntegrityError(
                        f"WAL index mismatch at line {line_number}: expected {expected_index}, got {entry.index}"
                    )
                if entry.previous_checksum != previous_checksum:
                    raise LogIntegrityError(f"WAL checksum chain mismatch at line {line_number}")
                if entry.checksum != _entry_checksum(entry.index, entry.previous_checksum, entry.payload):
                    raise LogIntegrityError(f"WAL payload checksum mismatch at line {line_number}")

                yield entry
                expected_index += 1
                previous_checksum = entry.checksum

    def next_index(self) -> int:
        with self._locked():
            last_entry = self._last_entry_unlocked()
            return 1 if last_entry is None else last_entry.index + 1

    def rewrite_excluding(
        self,
        predicate: Callable[[dict[str, object]], bool],
    ) -> int:
        """Atomically rewrite the WAL without payloads selected by predicate."""
        with self._locked():
            entries = list(self._replay_unlocked())
            payloads = [
                dict(entry.payload)
                for entry in entries
                if not predicate(dict(entry.payload))
            ]
            removed = len(entries) - len(payloads)
            if removed <= 0:
                return 0

            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self.path.with_name(
                f".{self.path.name}.purge-{os.getpid()}-{threading.get_ident()}.tmp"
            )
            previous_checksum = ""
            with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
                for index, payload in enumerate(payloads, start=1):
                    checksum = _entry_checksum(index, previous_checksum, payload)
                    record = {
                        "index": index,
                        "previous_checksum": previous_checksum,
                        "checksum": checksum,
                        "payload": payload,
                    }
                    handle.write(
                        json.dumps(
                            record,
                            ensure_ascii=False,
                            separators=(",", ":"),
                            allow_nan=False,
                        )
                    )
                    handle.write("\n")
                    previous_checksum = checksum
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.path)
            return removed

    def _last_entry_unlocked(self) -> WalEntry | None:
        last_entry = None
        for entry in self._replay_unlocked():
            last_entry = entry
        return last_entry


def _load_record(line: str, line_number: int) -> dict[str, object]:
    try:
        record = json.loads(line)
    except json.JSONDecodeError as exc:
        raise LogIntegrityError(f"Invalid WAL JSON at line {line_number}") from exc
    if not isinstance(record, dict):
        raise LogIntegrityError(f"Invalid WAL record at line {line_number}")
    return record


def _entry_from_record(record: dict[str, object], line_number: int) -> WalEntry:
    try:
        index = record["index"]
        previous_checksum = record["previous_checksum"]
        checksum = record["checksum"]
        payload = record["payload"]
    except KeyError as exc:
        raise LogIntegrityError(f"Missing WAL field at line {line_number}: {exc.args[0]}") from exc

    if not isinstance(index, int) or isinstance(index, bool):
        raise LogIntegrityError(f"Invalid WAL index at line {line_number}")
    if not isinstance(previous_checksum, str) or not isinstance(checksum, str):
        raise LogIntegrityError(f"Invalid WAL checksum at line {line_number}")
    if not isinstance(payload, dict):
        raise LogIntegrityError(f"Invalid WAL payload at line {line_number}")

    return WalEntry(
        index=index,
        previous_checksum=previous_checksum,
        checksum=checksum,
        payload=payload,
    )


def _canonical_payload(payload: dict[str, object]) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


def _entry_checksum(index: int, previous_checksum: str, payload: dict[str, object]) -> str:
    canonical_payload = _canonical_payload(payload)
    return hashlib.sha256(f"{index}|{previous_checksum}|{canonical_payload}".encode("utf-8")).hexdigest()
