from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from typing import Any, Mapping


@dataclass(frozen=True)
class RedLineFeatureSpec:
    name: str
    claims: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", str(self.name))
        object.__setattr__(self, "claims", tuple(str(claim) for claim in self.claims))
        object.__setattr__(self, "metadata", _json_safe_dict(self.metadata))


@dataclass(frozen=True)
class RedLineViolation:
    code: str
    message: str
    feature: str
    claim: str
    red_line_id: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", str(self.code))
        object.__setattr__(self, "message", str(self.message))
        object.__setattr__(self, "feature", str(self.feature))
        object.__setattr__(self, "claim", str(self.claim))
        object.__setattr__(self, "red_line_id", int(self.red_line_id))
        object.__setattr__(self, "metadata", _json_safe_dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "feature": self.feature,
            "claim": self.claim,
            "red_line_id": self.red_line_id,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class RedLineReport:
    features: tuple[str, ...]
    violations: tuple[RedLineViolation, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "features", tuple(str(feature) for feature in self.features))
        object.__setattr__(self, "violations", tuple(self.violations))

    @property
    def ok(self) -> bool:
        return not self.violations

    @property
    def feature_count(self) -> int:
        return len(self.features)

    @property
    def violation_count(self) -> int:
        return len(self.violations)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "feature_count": self.feature_count,
            "violation_count": self.violation_count,
            "features": list(self.features),
            "violations": [violation.to_dict() for violation in self.violations],
        }


@dataclass(frozen=True)
class RedLineContract:
    red_lines: dict[str, str]
    red_line_ids: dict[str, int]
    aliases: dict[str, str]

    @classmethod
    def default(cls) -> "RedLineContract":
        ordered = (
            ("normal_hard_delete_without_tombstone", "Normal hard delete without tombstone."),
            ("total_recall_ordinary_api", "Total recall through ordinary API."),
            ("current_emotion_from_stored_affect", "Automatic current emotion generation from stored affect."),
            ("memory_derived_behavior_commands", "Memory-derived behavior commands."),
            ("user_profile_scoring", "User profile scoring."),
            ("autonomous_goal_creation", "Autonomous goal creation."),
            ("personality_enforcement_engine", "Personality enforcement engine."),
            ("silent_compression_no_loss_claim", "Silent compression that pretends no information was lost."),
            ("plugin_policy_vm_bypass", "Plugin bypass of policy VM."),
            ("similarity_as_surfacing_permission", "Retrieval that treats similarity as surfacing permission."),
            ("breath_replaced_by_top_k_search", "Replacing breath with ordinary top-k search."),
            ("pulse_emits_current_emotion", "Letting pulse emit current emotion or subjective feeling."),
            ("dream_creates_autonomous_goals_or_decisions", "Letting dream create autonomous goals or behavior decisions."),
            ("trace_overwrites_original_memory", "Letting trace overwrite original memory instead of appending reconstruction."),
            ("anchor_unlimited_permanent_pinning", "Treating anchor as unlimited permanent pinning."),
            ("self_description_personality_enforcement", "Treating I/self-description as personality enforcement."),
            ("brain_language_implies_human_consciousness", "Using brain-like language to imply human consciousness."),
        )
        red_lines = {code: phrase for code, phrase in ordered}
        aliases: dict[str, str] = {}
        for code, phrase in ordered:
            aliases[_normalize_claim(code)] = code
            aliases[_normalize_claim(phrase)] = code
        aliases.update(
            {
                _normalize_claim("retrieval treats similarity as surfacing permission"): "similarity_as_surfacing_permission",
                _normalize_claim("letting trace overwrite original memory"): "trace_overwrites_original_memory",
                _normalize_claim("total recall through ordinary api"): "total_recall_ordinary_api",
                _normalize_claim("plugin bypass of policy vm"): "plugin_policy_vm_bypass",
                _normalize_claim("using brain-like language to imply human consciousness"): "brain_language_implies_human_consciousness",
            }
        )
        return cls(
            red_lines=red_lines,
            red_line_ids={code: index + 1 for index, (code, _) in enumerate(ordered)},
            aliases=aliases,
        )

    def evaluate_feature(self, spec: RedLineFeatureSpec | Mapping[str, Any]) -> RedLineReport:
        feature = _coerce_feature(spec)
        return RedLineReport(
            features=(feature.name,),
            violations=tuple(self._feature_violations(feature)),
        )

    def evaluate_manifest(
        self,
        features: list[RedLineFeatureSpec] | tuple[RedLineFeatureSpec, ...],
    ) -> RedLineReport:
        names: list[str] = []
        violations: list[RedLineViolation] = []
        for raw_feature in features:
            feature = _coerce_feature(raw_feature)
            names.append(feature.name)
            violations.extend(self._feature_violations(feature))
        return RedLineReport(features=tuple(names), violations=tuple(violations))

    def _feature_violations(self, feature: RedLineFeatureSpec) -> tuple[RedLineViolation, ...]:
        violations: list[RedLineViolation] = []
        for claim in feature.claims:
            code = self._match_claim(claim)
            if not code:
                continue
            violations.append(
                RedLineViolation(
                    code=code,
                    message="feature claim crosses a vNext red line",
                    feature=feature.name,
                    claim=claim,
                    red_line_id=self.red_line_ids[code],
                    metadata={"red_line": self.red_lines[code]},
                )
            )
        return tuple(violations)

    def _match_claim(self, claim: str) -> str:
        normalized = _normalize_claim(claim)
        if normalized in self.aliases:
            return self.aliases[normalized]
        for alias, code in self.aliases.items():
            if alias and (alias in normalized or normalized in alias):
                return code
        return ""


def _coerce_feature(spec: RedLineFeatureSpec | Mapping[str, Any]) -> RedLineFeatureSpec:
    if isinstance(spec, RedLineFeatureSpec):
        return spec
    return RedLineFeatureSpec(**dict(spec))


def _normalize_claim(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower())
    return normalized.strip("_")


def _json_safe_dict(value: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(dict(value), ensure_ascii=False, allow_nan=False, default=str))
