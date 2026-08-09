from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any, Iterable, Mapping


_ALLOWED_MEMORY_HEALTH_METRICS = {
    "trace_count_by_state",
    "unresolved_trace_count",
    "average_accessibility",
    "decay_distribution",
    "tombstone_count",
    "projection_lag",
    "ledger_replay_time",
    "surfacing_rejection_reasons",
    "archive_growth",
    "compression_lineage_depth",
}

_FORBIDDEN_USER_VALUE_METRICS = {
    "user_loyalty_score",
    "user_emotional_dependency_score",
    "persuasion_score",
    "manipulation_success_score",
    "personality_compliance_score",
}

_FORBIDDEN_LABEL_TOKENS = _FORBIDDEN_USER_VALUE_METRICS | {
    "user_value",
    "dependency_score",
    "emotional_dependency",
    "persuasion",
    "manipulation",
    "compliance_score",
}


@dataclass(frozen=True)
class ObservabilityMetricSpec:
    name: str
    value: Any = None
    labels: Mapping[str, Any] = field(default_factory=dict)
    description: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _normalize_metric_name(self.name))
        object.__setattr__(self, "labels", _json_safe(dict(self.labels)))
        object.__setattr__(self, "description", str(self.description or ""))

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ObservabilityMetricSpec":
        return cls(
            name=str(payload.get("name") or payload.get("metric_name") or ""),
            value=payload.get("value"),
            labels=payload.get("labels") if isinstance(payload.get("labels"), Mapping) else {},
            description=str(payload.get("description") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(
            {
                "name": self.name,
                "value": self.value,
                "labels": dict(self.labels),
                "description": self.description,
            }
        )


@dataclass(frozen=True)
class ObservabilityDecision:
    metric_name: str
    allowed: bool
    reason: str
    metric_family: str = ""
    forbidden_metric: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "metric_name", _normalize_metric_name(self.metric_name))
        object.__setattr__(self, "reason", str(self.reason))
        object.__setattr__(self, "metric_family", str(self.metric_family))
        object.__setattr__(self, "forbidden_metric", _normalize_metric_name(self.forbidden_metric))

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric_name": self.metric_name,
            "allowed": self.allowed,
            "reason": self.reason,
            "metric_family": self.metric_family,
            "forbidden_metric": self.forbidden_metric,
        }


@dataclass(frozen=True)
class ObservabilityReport:
    decisions: tuple[ObservabilityDecision, ...]

    @property
    def ok(self) -> bool:
        return all(decision.allowed for decision in self.decisions)

    @property
    def metric_count(self) -> int:
        return len(self.decisions)

    @property
    def allowed_count(self) -> int:
        return sum(1 for decision in self.decisions if decision.allowed)

    @property
    def rejected_count(self) -> int:
        return self.metric_count - self.allowed_count

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "metric_count": self.metric_count,
            "allowed_count": self.allowed_count,
            "rejected_count": self.rejected_count,
            "decisions": [decision.to_dict() for decision in self.decisions],
        }


@dataclass(frozen=True)
class ObservabilityMetricBoundary:
    allowed_memory_health_metrics: frozenset[str] = frozenset(_ALLOWED_MEMORY_HEALTH_METRICS)
    forbidden_user_value_metrics: frozenset[str] = frozenset(_FORBIDDEN_USER_VALUE_METRICS)
    forbidden_label_tokens: frozenset[str] = frozenset(_FORBIDDEN_LABEL_TOKENS)

    @classmethod
    def default(cls) -> "ObservabilityMetricBoundary":
        return cls()

    def evaluate_metric(self, metric: ObservabilityMetricSpec | Mapping[str, Any]) -> ObservabilityDecision:
        spec = _coerce_metric_spec(metric)
        forbidden_label = self._first_forbidden_label(spec.labels)
        if forbidden_label:
            return ObservabilityDecision(
                metric_name=spec.name,
                allowed=False,
                reason="forbidden metric label",
                forbidden_metric=forbidden_label,
            )
        if spec.name in self.forbidden_user_value_metrics:
            return ObservabilityDecision(
                metric_name=spec.name,
                allowed=False,
                reason="forbidden user-value metric",
                forbidden_metric=spec.name,
            )
        if spec.name not in self.allowed_memory_health_metrics:
            return ObservabilityDecision(
                metric_name=spec.name,
                allowed=False,
                reason="unknown metric",
            )
        return ObservabilityDecision(
            metric_name=spec.name,
            allowed=True,
            reason="allowed",
            metric_family="memory_health",
        )

    def evaluate_manifest(self, metrics: Iterable[ObservabilityMetricSpec | Mapping[str, Any]]) -> ObservabilityReport:
        return ObservabilityReport(tuple(self.evaluate_metric(metric) for metric in metrics))

    def _first_forbidden_label(self, labels: Mapping[str, Any]) -> str:
        for key in labels:
            normalized = _normalize_metric_name(key)
            if normalized in self.forbidden_label_tokens:
                return normalized
        return ""


def _coerce_metric_spec(value: ObservabilityMetricSpec | Mapping[str, Any]) -> ObservabilityMetricSpec:
    if isinstance(value, ObservabilityMetricSpec):
        return value
    return ObservabilityMetricSpec.from_mapping(value)


def _normalize_metric_name(value: object) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False, default=str))
