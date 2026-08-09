from pathlib import Path
import json

import frontmatter

from ombrebrain.protocol.schemas import ActorKind, MemoryEvent, MemoryType, Visibility


def _memory_type(value: object) -> MemoryType:
    if isinstance(value, MemoryType):
        return value
    if value is None:
        return MemoryType.DYNAMIC

    try:
        return MemoryType(str(value).strip().lower())
    except ValueError:
        return MemoryType.DYNAMIC


def _legacy_tags(value: object) -> list[object]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _json_safe(value: object) -> object:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False, default=str))


def bucket_markdown_to_event(path: str | Path) -> MemoryEvent:
    bucket_path = Path(path)
    post = frontmatter.load(bucket_path)
    legacy = post.metadata
    metadata = {
        "legacy_metadata": _json_safe(legacy),
        "legacy_bucket_id": str(legacy.get("id", "")),
        "legacy_name": str(legacy.get("name", bucket_path.stem)),
        "legacy_path": str(bucket_path),
        "legacy_tags": _json_safe(_legacy_tags(legacy.get("tags"))),
    }

    return MemoryEvent.new(
        actor=ActorKind.SYSTEM,
        actor_name="v2.3.22-migration",
        memory_type=_memory_type(legacy.get("type")),
        content=post.content.strip(),
        visibility=Visibility.PRIVATE,
        importance=legacy.get("importance", 5),
        source_chain=("legacy_bucket",),
        metadata=metadata,
    )
