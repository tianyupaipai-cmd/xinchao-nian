from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
from typing import Any


class CommandKind(Enum):
    HOLD = "hold"
    BREATH = "breath"
    TRACE = "trace"
    DECAY = "decay"
    IMPORT = "import"
    MIGRATE = "migrate"
    SYNC = "sync"
    WEB_ROUTE = "web_route"
    UNKNOWN = "unknown"


class ProjectionKind(Enum):
    FABRIC_EVENT = "fabric_event"
    BUCKET_MARKDOWN = "bucket_markdown"
    VECTOR_INDEX = "vector_index"
    DASHBOARD_STATE = "dashboard_state"
    DEPLOYMENT_STATE = "deployment_state"
    EXTERNAL_NETWORK = "external_network"


@dataclass(frozen=True)
class MemoryCommand:
    id: str
    kind: CommandKind
    payload: dict[str, Any] = field(default_factory=dict)
    actor_name: str = "legacy-runtime"
    source: str = "legacy"
    created_at: str = "1970-01-01T00:00:00+00:00"

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _coerce_enum(CommandKind, self.kind))
        object.__setattr__(self, "payload", _sanitize_payload(self.payload))
        object.__setattr__(self, "actor_name", str(self.actor_name or "legacy-runtime"))
        object.__setattr__(self, "source", str(self.source or "legacy"))
        object.__setattr__(self, "created_at", str(self.created_at))

    @classmethod
    def new(
        cls,
        *,
        kind: CommandKind | str,
        payload: Mapping[str, Any] | None = None,
        actor_name: str = "legacy-runtime",
        source: str = "legacy",
        created_at: str = "1970-01-01T00:00:00+00:00",
    ) -> "MemoryCommand":
        normalized = {
            "kind": _coerce_enum(CommandKind, kind).value,
            "payload": _sanitize_payload(dict(payload or {})),
            "actor_name": str(actor_name or "legacy-runtime"),
            "source": str(source or "legacy"),
            "created_at": str(created_at),
        }
        return cls(id=_stable_id(normalized), **normalized)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "payload": dict(self.payload),
            "actor_name": self.actor_name,
            "source": self.source,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class ProjectionStep:
    kind: ProjectionKind
    action: str
    surface: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _coerce_enum(ProjectionKind, self.kind))
        object.__setattr__(self, "action", str(self.action))
        object.__setattr__(self, "surface", str(self.surface))

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind.value,
            "action": self.action,
            "surface": self.surface,
        }


@dataclass(frozen=True)
class CommandPlan:
    command_id: str
    command_kind: CommandKind
    writes_memory: bool
    projections: tuple[ProjectionStep, ...]
    policy_tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "command_kind", _coerce_enum(CommandKind, self.command_kind))
        object.__setattr__(self, "projections", tuple(self.projections))
        object.__setattr__(self, "policy_tags", tuple(str(item) for item in self.policy_tags))

    def to_dict(self) -> dict[str, Any]:
        return {
            "command_id": self.command_id,
            "command_kind": self.command_kind.value,
            "writes_memory": self.writes_memory,
            "policy_tags": list(self.policy_tags),
            "projections": [step.to_dict() for step in self.projections],
        }


class MemoryCommandRouter:
    def __init__(self, projection_map: Mapping[CommandKind, tuple[ProjectionStep, ...]]):
        self._projection_map = dict(projection_map)

    @classmethod
    def default(cls) -> "MemoryCommandRouter":
        return cls(
            {
                CommandKind.HOLD: (
                    ProjectionStep(ProjectionKind.FABRIC_EVENT, "append", "memory_fabric"),
                    ProjectionStep(ProjectionKind.BUCKET_MARKDOWN, "upsert", "buckets"),
                    ProjectionStep(ProjectionKind.VECTOR_INDEX, "upsert", "embeddings"),
                    ProjectionStep(ProjectionKind.DASHBOARD_STATE, "refresh", "dashboard"),
                ),
                CommandKind.BREATH: (
                    ProjectionStep(ProjectionKind.FABRIC_EVENT, "trace-read", "memory_fabric"),
                    ProjectionStep(ProjectionKind.DASHBOARD_STATE, "refresh", "dashboard"),
                ),
                CommandKind.TRACE: (
                    ProjectionStep(ProjectionKind.FABRIC_EVENT, "append", "memory_fabric"),
                    ProjectionStep(ProjectionKind.BUCKET_MARKDOWN, "patch", "buckets"),
                    ProjectionStep(ProjectionKind.VECTOR_INDEX, "sync", "embeddings"),
                    ProjectionStep(ProjectionKind.DASHBOARD_STATE, "refresh", "dashboard"),
                ),
                CommandKind.DECAY: (
                    ProjectionStep(ProjectionKind.FABRIC_EVENT, "append", "memory_fabric"),
                    ProjectionStep(ProjectionKind.BUCKET_MARKDOWN, "archive", "buckets"),
                    ProjectionStep(ProjectionKind.VECTOR_INDEX, "backfill-missing", "embeddings"),
                ),
                CommandKind.IMPORT: (
                    ProjectionStep(ProjectionKind.FABRIC_EVENT, "append", "memory_fabric"),
                    ProjectionStep(ProjectionKind.BUCKET_MARKDOWN, "bulk-upsert", "buckets"),
                    ProjectionStep(ProjectionKind.VECTOR_INDEX, "bulk-upsert", "embeddings"),
                    ProjectionStep(ProjectionKind.DASHBOARD_STATE, "refresh", "dashboard"),
                ),
                CommandKind.MIGRATE: (
                    ProjectionStep(ProjectionKind.FABRIC_EVENT, "append", "memory_fabric"),
                    ProjectionStep(ProjectionKind.BUCKET_MARKDOWN, "bulk-merge", "buckets"),
                    ProjectionStep(ProjectionKind.VECTOR_INDEX, "rebuild", "embeddings"),
                    ProjectionStep(ProjectionKind.DASHBOARD_STATE, "refresh", "dashboard"),
                ),
                CommandKind.SYNC: (
                    ProjectionStep(ProjectionKind.FABRIC_EVENT, "append", "memory_fabric"),
                    ProjectionStep(ProjectionKind.EXTERNAL_NETWORK, "github-tree", "github"),
                ),
                CommandKind.WEB_ROUTE: (
                    ProjectionStep(ProjectionKind.FABRIC_EVENT, "trace-route", "memory_fabric"),
                    ProjectionStep(ProjectionKind.DASHBOARD_STATE, "refresh", "dashboard"),
                ),
                CommandKind.UNKNOWN: (
                    ProjectionStep(ProjectionKind.FABRIC_EVENT, "trace", "memory_fabric"),
                ),
            }
        )

    def plan(self, command: MemoryCommand) -> CommandPlan:
        projections = self._projection_map.get(command.kind, self._projection_map[CommandKind.UNKNOWN])
        return CommandPlan(
            command_id=command.id,
            command_kind=command.kind,
            writes_memory=_writes_memory(command),
            projections=projections,
            policy_tags=_policy_tags(command),
        )


def _writes_memory(command: MemoryCommand) -> bool:
    if command.kind in {CommandKind.BREATH, CommandKind.WEB_ROUTE, CommandKind.UNKNOWN}:
        return False
    if command.kind == CommandKind.SYNC:
        return False
    return True


def _policy_tags(command: MemoryCommand) -> tuple[str, ...]:
    tags: list[str] = []
    if command.kind == CommandKind.TRACE and bool(command.payload.get("delete")):
        tags.extend(("trace-delete", "vector-delete"))
    if command.kind == CommandKind.HOLD and bool(command.payload.get("pinned")):
        tags.append("permanent-pinned")
    if command.kind == CommandKind.WEB_ROUTE:
        tags.append("operator-route")
    if command.kind == CommandKind.SYNC:
        tags.append("network-side-effect")
    return tuple(tags)


_SENSITIVE_PARTS = (
    "token",
    "secret",
    "password",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "session",
    "oauth",
)


def _sanitize_payload(value: Any) -> Any:
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key_str = str(key)
            if any(part in key_str.lower() for part in _SENSITIVE_PARTS):
                sanitized[key_str] = "[REDACTED]"
            else:
                sanitized[key_str] = _sanitize_payload(item)
        return sanitized
    if isinstance(value, (list, tuple)):
        return [_sanitize_payload(item) for item in value]
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False, default=str))


def _coerce_enum(enum_type: type[Enum], value: object) -> Enum:
    if isinstance(value, enum_type):
        return value
    return enum_type(str(value))


def _stable_id(payload: dict[str, Any]) -> str:
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return f"cmd_{hashlib.sha256(serialized.encode('utf-8')).hexdigest()[:32]}"
