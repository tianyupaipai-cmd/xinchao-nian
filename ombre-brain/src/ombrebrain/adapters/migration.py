from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ombrebrain.adapters.bucket_adapter import bucket_markdown_to_event
from ombrebrain.fabric.storage.engine import MemoryFabric


_BUCKET_DIRS = ("dynamic", "permanent", "archive", "feel", "plans", "letters")


@dataclass(frozen=True)
class ConvertedFile:
    path: str
    event_id: str
    memory_type: str


@dataclass(frozen=True)
class SkippedFile:
    path: str
    reason: str


@dataclass(frozen=True)
class MigrationError:
    path: str
    message: str


@dataclass(frozen=True)
class MigrationReport:
    converted: tuple[ConvertedFile, ...]
    skipped: tuple[SkippedFile, ...]
    errors: tuple[MigrationError, ...]
    vector_rebuild_required: bool


def migrate_bucket_tree(bucket_root: str | Path, fabric: MemoryFabric) -> MigrationReport:
    root = Path(bucket_root)
    if not root.exists():
        return MigrationReport(converted=(), skipped=(), errors=(), vector_rebuild_required=False)

    converted: list[ConvertedFile] = []
    skipped: list[SkippedFile] = []
    errors: list[MigrationError] = []

    for path in _iter_bucket_files(root):
        relative = _relative_path(root, path)
        if path.suffix.lower() != ".md":
            skipped.append(SkippedFile(path=relative, reason="not markdown"))
            continue

        try:
            event = bucket_markdown_to_event(path)
            fabric.append_event(event)
            converted.append(
                ConvertedFile(path=relative, event_id=event.id, memory_type=event.memory_type.value)
            )
        except Exception as exc:  # noqa: BLE001 - migration reports per-file failures.
            errors.append(MigrationError(path=relative, message=str(exc)))

    return MigrationReport(
        converted=tuple(converted),
        skipped=tuple(skipped),
        errors=tuple(errors),
        vector_rebuild_required=bool(converted),
    )


def _iter_bucket_files(root: Path) -> tuple[Path, ...]:
    files: list[Path] = []
    for dirname in _BUCKET_DIRS:
        directory = root / dirname
        if not directory.exists():
            continue
        files.extend(path for path in directory.rglob("*") if path.is_file())
    return tuple(sorted(files, key=lambda path: _relative_path(root, path)))


def _relative_path(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()
