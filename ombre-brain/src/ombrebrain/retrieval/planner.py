from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any


@dataclass(frozen=True)
class QueryIntent:
    query: str
    operation: str
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "query", str(self.query))
        object.__setattr__(self, "operation", str(self.operation))
        object.__setattr__(self, "tags", tuple(str(tag) for tag in self.tags))

    def to_dict(self) -> dict[str, Any]:
        return {"query": self.query, "operation": self.operation, "tags": list(self.tags)}


@dataclass(frozen=True)
class RetrievalStage:
    name: str
    purpose: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", str(self.name))
        object.__setattr__(self, "purpose", str(self.purpose))

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "purpose": self.purpose}


@dataclass(frozen=True)
class RetrievalPlan:
    intent: QueryIntent
    channels: tuple[str, ...]
    stages: tuple[RetrievalStage, ...]
    limit: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "channels", tuple(str(channel) for channel in self.channels))
        object.__setattr__(self, "stages", tuple(self.stages))
        object.__setattr__(self, "limit", max(1, int(self.limit)))

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(
            {
                **self.intent.to_dict(),
                "channels": list(self.channels),
                "stages": [stage.to_dict() for stage in self.stages],
                "limit": self.limit,
            }
        )


@dataclass(frozen=True)
class QueryPlanner:
    default_channels: tuple[str, ...] = ("dynamic", "permanent", "feel", "letter")

    @classmethod
    def default(cls) -> "QueryPlanner":
        return cls()

    def plan(self, payload: dict[str, Any] | None = None, *, operation: str = "breath") -> RetrievalPlan:
        data = _json_safe(payload or {})
        query = str(data.get("query") or data.get("q") or "")
        explicit_type = str(data.get("type") or "").strip().lower()
        channels = (explicit_type,) if explicit_type in self.default_channels else self.default_channels
        tags = (f"type:{explicit_type}",) if explicit_type in self.default_channels else ()
        return RetrievalPlan(
            intent=QueryIntent(query=query, operation=operation, tags=tags),
            channels=channels,
            stages=_default_stages(),
            limit=int(data.get("max_results") or data.get("limit") or 8),
        )


def _default_stages() -> tuple[RetrievalStage, ...]:
    return (
        RetrievalStage("lexical_prefilter", "keyword and field prefilter"),
        RetrievalStage("semantic_vector_probe", "embedding candidate expansion"),
        RetrievalStage("recency_importance_merge", "merge recency and importance signals"),
        RetrievalStage("policy_visibility_filter", "remove invisible or protected diagnostic-only records"),
        RetrievalStage("explainable_rerank", "produce stable ranked output with trace reasons"),
    )


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False, default=str))
