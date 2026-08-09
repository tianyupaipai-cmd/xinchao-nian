from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import math


class ActorKind(Enum):
    USER = "user"
    CODEX = "codex"
    CLAUDE = "claude"
    GPT = "gpt"
    GEMINI = "gemini"
    MCP_TOOL = "mcp_tool"
    WEB_DASHBOARD = "web_dashboard"
    SYSTEM = "system"


class MemoryType(Enum):
    DYNAMIC = "dynamic"
    PERMANENT = "permanent"
    TRACE = "trace"
    LETTER = "letter"
    PLAN = "plan"
    FEEL = "feel"


class Visibility(Enum):
    PRIVATE = "private"
    INTERNAL = "internal"
    SHARED = "shared"


def _clamp_float(value: float, minimum: float, maximum: float) -> float:
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError("confidence must be finite")
    return max(minimum, min(maximum, numeric))


def _clamp_int(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, int(value)))


@dataclass(frozen=True)
class MemoryEvent:
    id: str
    actor: ActorKind
    actor_name: str
    memory_type: MemoryType
    content: str
    visibility: Visibility
    session_id: str | None = None
    task_id: str | None = None
    source_chain: tuple[str, ...] = field(default_factory=tuple)
    parent_event_ids: tuple[str, ...] = field(default_factory=tuple)
    cluster_term: int = 0
    cluster_index: int = 0
    created_at: str = "1970-01-01T00:00:00+00:00"
    confidence: float = 1.0
    importance: int = 5
    vector_state: str = "pending"
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "actor", _coerce_enum(ActorKind, self.actor))
        object.__setattr__(self, "memory_type", _coerce_enum(MemoryType, self.memory_type))
        object.__setattr__(self, "visibility", _coerce_enum(Visibility, self.visibility))
        object.__setattr__(self, "source_chain", tuple(self.source_chain))
        object.__setattr__(self, "parent_event_ids", tuple(str(item) for item in self.parent_event_ids))
        object.__setattr__(self, "cluster_term", int(self.cluster_term))
        object.__setattr__(self, "cluster_index", int(self.cluster_index))
        object.__setattr__(self, "created_at", str(self.created_at))
        object.__setattr__(self, "confidence", _clamp_float(self.confidence, 0.0, 1.0))
        object.__setattr__(self, "importance", _clamp_int(self.importance, 1, 10))
        object.__setattr__(self, "metadata", dict(self.metadata))

    @classmethod
    def new(
        cls,
        *,
        actor: ActorKind,
        actor_name: str,
        memory_type: MemoryType,
        content: str,
        visibility: Visibility,
        session_id: str | None = None,
        task_id: str | None = None,
        source_chain: list[str] | tuple[str, ...] = (),
        parent_event_ids: list[str] | tuple[str, ...] = (),
        cluster_term: int = 0,
        cluster_index: int = 0,
        created_at: str = "1970-01-01T00:00:00+00:00",
        confidence: float = 1.0,
        importance: int = 5,
        vector_state: str = "pending",
        metadata: dict[str, object] | None = None,
    ) -> "MemoryEvent":
        normalized = {
            "actor": _coerce_enum(ActorKind, actor).value,
            "actor_name": actor_name,
            "memory_type": _coerce_enum(MemoryType, memory_type).value,
            "content": content,
            "visibility": _coerce_enum(Visibility, visibility).value,
            "session_id": session_id,
            "task_id": task_id,
            "source_chain": list(source_chain),
            "parent_event_ids": [str(item) for item in parent_event_ids],
            "cluster_term": int(cluster_term),
            "cluster_index": int(cluster_index),
            "created_at": str(created_at),
            "confidence": _clamp_float(confidence, 0.0, 1.0),
            "importance": _clamp_int(importance, 1, 10),
            "vector_state": vector_state,
            "metadata": dict(metadata or {}),
        }
        event_id = _deterministic_id(normalized)
        return cls(id=event_id, **normalized)

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "actor": self.actor.value,
            "actor_name": self.actor_name,
            "memory_type": self.memory_type.value,
            "content": self.content,
            "visibility": self.visibility.value,
            "session_id": self.session_id,
            "task_id": self.task_id,
            "source_chain": list(self.source_chain),
            "parent_event_ids": list(self.parent_event_ids),
            "cluster_term": self.cluster_term,
            "cluster_index": self.cluster_index,
            "created_at": self.created_at,
            "confidence": self.confidence,
            "importance": self.importance,
            "vector_state": self.vector_state,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "MemoryEvent":
        data = dict(payload)
        derived_id = _deterministic_id(_id_payload(data))
        if "id" in data and str(data["id"]) != derived_id:
            raise ValueError("MemoryEvent id does not match payload")
        data["id"] = derived_id
        return cls(
            id=str(data["id"]),
            actor=_coerce_enum(ActorKind, data["actor"]),
            actor_name=str(data["actor_name"]),
            memory_type=_coerce_enum(MemoryType, data["memory_type"]),
            content=str(data["content"]),
            visibility=_coerce_enum(Visibility, data["visibility"]),
            session_id=_optional_str(data.get("session_id")),
            task_id=_optional_str(data.get("task_id")),
            source_chain=tuple(str(item) for item in data.get("source_chain", ())),
            parent_event_ids=tuple(str(item) for item in data.get("parent_event_ids", ())),
            cluster_term=int(data.get("cluster_term", 0)),
            cluster_index=int(data.get("cluster_index", 0)),
            created_at=str(data.get("created_at", "1970-01-01T00:00:00+00:00")),
            confidence=float(data.get("confidence", 1.0)),
            importance=int(data.get("importance", 5)),
            vector_state=str(data.get("vector_state", "pending")),
            metadata=_metadata_dict(data.get("metadata")),
        )

    def with_cluster_position(self, *, term: int, index: int) -> "MemoryEvent":
        return type(self).new(
            actor=self.actor,
            actor_name=self.actor_name,
            memory_type=self.memory_type,
            content=self.content,
            visibility=self.visibility,
            session_id=self.session_id,
            task_id=self.task_id,
            source_chain=self.source_chain,
            parent_event_ids=self.parent_event_ids,
            cluster_term=term,
            cluster_index=index,
            created_at=self.created_at,
            confidence=self.confidence,
            importance=self.importance,
            vector_state=self.vector_state,
            metadata=self.metadata,
        )


def _coerce_enum(enum_type: type[Enum], value: object) -> Enum:
    if isinstance(value, enum_type):
        return value
    return enum_type(str(value))


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _metadata_dict(value: object) -> dict[str, object]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    raise TypeError("metadata must be a dict")


def _deterministic_id(payload: dict[str, object]) -> str:
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    return f"mem_{digest[:32]}"


def _id_payload(payload: dict[str, object]) -> dict[str, object]:
    data = dict(payload)
    data.pop("id", None)
    return {
        "actor": _coerce_enum(ActorKind, data["actor"]).value,
        "actor_name": data["actor_name"],
        "memory_type": _coerce_enum(MemoryType, data["memory_type"]).value,
        "content": data["content"],
        "visibility": _coerce_enum(Visibility, data["visibility"]).value,
        "session_id": data.get("session_id"),
        "task_id": data.get("task_id"),
        "source_chain": list(data.get("source_chain", ())),
        "parent_event_ids": [str(item) for item in data.get("parent_event_ids", ())],
        "cluster_term": int(data.get("cluster_term", 0)),
        "cluster_index": int(data.get("cluster_index", 0)),
        "created_at": str(data.get("created_at", "1970-01-01T00:00:00+00:00")),
        "confidence": _clamp_float(float(data.get("confidence", 1.0)), 0.0, 1.0),
        "importance": _clamp_int(int(data.get("importance", 5)), 1, 10),
        "vector_state": data.get("vector_state", "pending"),
        "metadata": _metadata_dict(data.get("metadata")),
    }
