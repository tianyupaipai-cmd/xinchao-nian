from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
from typing import Any, Iterable, Mapping

from ombrebrain.policy.surfacing import SurfacePolicyVM


@dataclass(frozen=True)
class RetrievalWeights:
    semantic: float = 1.0
    lexical: float = 1.0
    temporal: float = 1.0
    affective: float = 1.0
    unresolved: float = 1.0
    promise: float = 1.0
    graph_neighbor: float = 1.0

    def to_dict(self) -> dict[str, float]:
        return {
            "semantic": float(self.semantic),
            "lexical": float(self.lexical),
            "temporal": float(self.temporal),
            "affective": float(self.affective),
            "unresolved": float(self.unresolved),
            "promise": float(self.promise),
            "graph_neighbor": float(self.graph_neighbor),
        }


@dataclass(frozen=True)
class RetrievalFeatures:
    semantic_similarity: float = 0.0
    lexical_similarity: float = 0.0
    temporal_proximity: float = 0.0
    affective_proximity: float = 0.0
    unresolved_relevance: float = 0.0
    promise_relevance: float = 0.0
    graph_neighbor_relevance: float = 0.0

    def candidate_score(self, weights: RetrievalWeights) -> float:
        return round(
            self.semantic_similarity * weights.semantic
            + self.lexical_similarity * weights.lexical
            + self.temporal_proximity * weights.temporal
            + self.affective_proximity * weights.affective
            + self.unresolved_relevance * weights.unresolved
            + self.promise_relevance * weights.promise
            + self.graph_neighbor_relevance * weights.graph_neighbor,
            6,
        )

    def to_dict(self) -> dict[str, float]:
        return {
            "semantic_similarity": float(self.semantic_similarity),
            "lexical_similarity": float(self.lexical_similarity),
            "temporal_proximity": float(self.temporal_proximity),
            "affective_proximity": float(self.affective_proximity),
            "unresolved_relevance": float(self.unresolved_relevance),
            "promise_relevance": float(self.promise_relevance),
            "graph_neighbor_relevance": float(self.graph_neighbor_relevance),
        }


@dataclass(frozen=True)
class RetrievalGates:
    accessibility: float = 1.0
    dignity: float = 1.0
    scarcity: float = 1.0
    intent: float = 1.0
    non_cognition: float = 1.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "accessibility", _clamp_gate(self.accessibility))
        object.__setattr__(self, "dignity", _clamp_gate(self.dignity))
        object.__setattr__(self, "scarcity", _clamp_gate(self.scarcity))
        object.__setattr__(self, "intent", _clamp_gate(self.intent))
        object.__setattr__(self, "non_cognition", _clamp_gate(self.non_cognition))

    def with_accessibility(self, accessibility: float) -> "RetrievalGates":
        return RetrievalGates(
            accessibility=accessibility,
            dignity=self.dignity,
            scarcity=self.scarcity,
            intent=self.intent,
            non_cognition=self.non_cognition,
        )

    @property
    def product(self) -> float:
        return round(
            self.accessibility
            * self.dignity
            * self.scarcity
            * self.intent
            * self.non_cognition,
            6,
        )

    def to_dict(self) -> dict[str, float]:
        return {
            "accessibility": self.accessibility,
            "dignity_gate": self.dignity,
            "scarcity_gate": self.scarcity,
            "intent_gate": self.intent,
            "non_cognition_gate": self.non_cognition,
        }


@dataclass(frozen=True)
class RetrievalCandidate:
    bucket: Mapping[str, Any]
    features: RetrievalFeatures = field(default_factory=RetrievalFeatures)
    gates: RetrievalGates = field(default_factory=RetrievalGates)
    source: str = ""


@dataclass(frozen=True)
class RetrievalScore:
    bucket_id: str
    candidate_score: float
    surface_score: float
    policy_allowed: bool
    policy_reasons: tuple[str, ...]
    mode: str
    features: RetrievalFeatures
    gates: RetrievalGates
    weights: RetrievalWeights
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(
            {
                "bucket_id": self.bucket_id,
                "candidate_score": self.candidate_score,
                "surface_score": self.surface_score,
                "policy_allowed": self.policy_allowed,
                "policy_reasons": list(self.policy_reasons),
                "mode": self.mode,
                "features": self.features.to_dict(),
                "gates": self.gates.to_dict(),
                "weights": self.weights.to_dict(),
                "source": self.source,
            }
        )


@dataclass(frozen=True)
class PolicyGatedRetrievalScorer:
    weights: RetrievalWeights = field(default_factory=RetrievalWeights)
    surface_policy: SurfacePolicyVM = field(default_factory=SurfacePolicyVM.default)

    @classmethod
    def default(cls) -> "PolicyGatedRetrievalScorer":
        return cls()

    def score_bucket(
        self,
        bucket: Mapping[str, Any],
        features: RetrievalFeatures | Mapping[str, Any] | None = None,
        *,
        gates: RetrievalGates | Mapping[str, Any] | None = None,
        mode: str = "search",
        source: str = "",
    ) -> RetrievalScore:
        normalized_features = _coerce_features(features)
        normalized_gates = _coerce_gates(gates)
        decision = self.surface_policy.evaluate_bucket(bucket, mode=mode)
        accessibility = normalized_gates.accessibility if decision.allowed else 0.0
        effective_gates = normalized_gates.with_accessibility(accessibility)
        candidate_score = normalized_features.candidate_score(self.weights)
        surface_score = round(candidate_score * effective_gates.product, 6)
        return RetrievalScore(
            bucket_id=decision.bucket_id,
            candidate_score=candidate_score,
            surface_score=surface_score,
            policy_allowed=decision.allowed,
            policy_reasons=tuple(decision.reasons),
            mode=decision.mode,
            features=normalized_features,
            gates=effective_gates,
            weights=self.weights,
            source=str(source or ""),
        )

    def rank(
        self,
        candidates: Iterable[RetrievalCandidate | Mapping[str, Any]],
        *,
        mode: str = "search",
        limit: int | None = None,
    ) -> list[RetrievalScore]:
        scores = [
            self.score_bucket(
                candidate.bucket,
                candidate.features,
                gates=candidate.gates,
                mode=mode,
                source=candidate.source,
            )
            for candidate in (_coerce_candidate(item) for item in candidates)
        ]
        ranked = sorted(
            scores,
            key=lambda score: (score.surface_score, score.candidate_score, score.bucket_id),
            reverse=True,
        )
        if limit is None:
            return ranked
        return ranked[: max(0, int(limit))]


def _coerce_candidate(value: RetrievalCandidate | Mapping[str, Any]) -> RetrievalCandidate:
    if isinstance(value, RetrievalCandidate):
        return value
    return RetrievalCandidate(
        bucket=value.get("bucket") if isinstance(value.get("bucket"), Mapping) else value,
        features=_coerce_features(value.get("features") if isinstance(value.get("features"), Mapping) else None),
        gates=_coerce_gates(value.get("gates") if isinstance(value.get("gates"), Mapping) else None),
        source=str(value.get("source") or ""),
    )


def _coerce_features(value: RetrievalFeatures | Mapping[str, Any] | None) -> RetrievalFeatures:
    if isinstance(value, RetrievalFeatures):
        return value
    if isinstance(value, Mapping):
        return RetrievalFeatures(
            semantic_similarity=_float_value(value.get("semantic_similarity")),
            lexical_similarity=_float_value(value.get("lexical_similarity")),
            temporal_proximity=_float_value(value.get("temporal_proximity")),
            affective_proximity=_float_value(value.get("affective_proximity")),
            unresolved_relevance=_float_value(value.get("unresolved_relevance")),
            promise_relevance=_float_value(value.get("promise_relevance")),
            graph_neighbor_relevance=_float_value(value.get("graph_neighbor_relevance")),
        )
    return RetrievalFeatures()


def _coerce_gates(value: RetrievalGates | Mapping[str, Any] | None) -> RetrievalGates:
    if isinstance(value, RetrievalGates):
        return value
    if isinstance(value, Mapping):
        return RetrievalGates(
            accessibility=_float_value(value.get("accessibility"), default=1.0),
            dignity=_float_value(value.get("dignity") or value.get("dignity_gate"), default=1.0),
            scarcity=_float_value(value.get("scarcity") or value.get("scarcity_gate"), default=1.0),
            intent=_float_value(value.get("intent") or value.get("intent_gate"), default=1.0),
            non_cognition=_float_value(
                value.get("non_cognition") or value.get("non_cognition_gate"),
                default=1.0,
            ),
        )
    return RetrievalGates()


def _float_value(value: object, *, default: float = 0.0) -> float:
    try:
        numeric = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return default
    return numeric if math.isfinite(numeric) else default


def _clamp_gate(value: object) -> float:
    return max(0.0, min(1.0, round(_float_value(value, default=1.0), 6)))


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False, default=str))
