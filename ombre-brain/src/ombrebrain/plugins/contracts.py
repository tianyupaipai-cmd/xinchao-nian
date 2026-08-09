from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping


_ALLOWED_PLUGIN_TYPES = {
    "projection",
    "embedding_provider",
    "vault_exporter",
    "dashboard_panel",
    "search_analyzer",
    "migration_checker",
    "decay_visualizer",
    "integrity_auditor",
}

_FORBIDDEN_PLUGIN_TYPES = {
    "autonomous_goal",
    "autonomous_goal_plugin",
    "personality_engine",
    "personality_engine_plugin",
    "current_emotion_generator",
    "belief_updater",
    "belief_updater_plugin",
    "answer_controller",
    "answer_controller_plugin",
    "user_scoring",
    "user_scoring_plugin",
}

_FORBIDDEN_COGNITIVE_CAPABILITIES = {
    "issue_commands",
    "set_current_emotion",
    "create_autonomous_goal",
    "generate_current_emotion",
    "personality_engine",
    "belief_updater",
    "update_belief",
    "answer_controller",
    "control_answer",
    "user_scoring",
    "score_user",
}


@dataclass(frozen=True)
class PluginManifest:
    name: str
    version: str
    plugin_type: str
    capabilities: tuple[str, ...]
    requested_surfaces: tuple[str, ...] = ()
    side_effect_mode: str = "read_only"

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PluginManifest":
        data = _json_safe(payload)
        return cls(
            name=str(data["name"]),
            version=str(data["version"]),
            plugin_type=str(data.get("plugin_type") or data.get("type") or "projection"),
            capabilities=_capabilities_from_payload(data.get("capabilities", ())),
            requested_surfaces=tuple(str(item) for item in data.get("requested_surfaces", ())),
            side_effect_mode=str(data.get("side_effect_mode") or "read_only"),
        )

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("plugin name is required")
        if not self.version:
            raise ValueError("plugin version is required")
        if not self.plugin_type:
            raise ValueError("plugin type is required")
        if not self.capabilities:
            raise ValueError("plugin must declare at least one capability")
        object.__setattr__(self, "plugin_type", _normalize_token(self.plugin_type))
        object.__setattr__(self, "capabilities", tuple(str(item) for item in self.capabilities))
        object.__setattr__(self, "requested_surfaces", tuple(str(item) for item in self.requested_surfaces))
        object.__setattr__(self, "side_effect_mode", str(self.side_effect_mode))

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "plugin_type": self.plugin_type,
            "capabilities": list(self.capabilities),
            "requested_surfaces": list(self.requested_surfaces),
            "side_effect_mode": self.side_effect_mode,
        }


@dataclass(frozen=True)
class PluginAgencyDecision:
    allowed: bool
    reason: str
    plugin_type: str
    forbidden_plugin_type: str = ""
    forbidden_capabilities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "reason", str(self.reason))
        object.__setattr__(self, "plugin_type", _normalize_token(self.plugin_type))
        object.__setattr__(self, "forbidden_plugin_type", _normalize_token(self.forbidden_plugin_type))
        object.__setattr__(self, "forbidden_capabilities", tuple(str(item) for item in self.forbidden_capabilities))

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "plugin_type": self.plugin_type,
            "forbidden_plugin_type": self.forbidden_plugin_type,
            "forbidden_capabilities": list(self.forbidden_capabilities),
        }


@dataclass(frozen=True)
class PluginAgencyBoundary:
    allowed_plugin_types: frozenset[str] = frozenset(_ALLOWED_PLUGIN_TYPES)
    forbidden_plugin_types: frozenset[str] = frozenset(_FORBIDDEN_PLUGIN_TYPES)
    forbidden_cognitive_capabilities: frozenset[str] = frozenset(_FORBIDDEN_COGNITIVE_CAPABILITIES)

    @classmethod
    def default(cls) -> "PluginAgencyBoundary":
        return cls()

    def evaluate(self, manifest: PluginManifest) -> PluginAgencyDecision:
        plugin_type = _normalize_token(manifest.plugin_type)
        if plugin_type in self.forbidden_plugin_types or plugin_type not in self.allowed_plugin_types:
            return PluginAgencyDecision(
                allowed=False,
                reason="forbidden plugin type",
                plugin_type=plugin_type,
                forbidden_plugin_type=plugin_type,
            )
        forbidden_capabilities = tuple(
            capability
            for capability in manifest.capabilities
            if _is_forbidden_capability(capability, self.forbidden_cognitive_capabilities)
        )
        if forbidden_capabilities:
            return PluginAgencyDecision(
                allowed=False,
                reason="forbidden cognitive capability",
                plugin_type=plugin_type,
                forbidden_capabilities=forbidden_capabilities,
            )
        return PluginAgencyDecision(allowed=True, reason="allowed", plugin_type=plugin_type)


@dataclass(frozen=True)
class PluginSandboxDecision:
    allowed: bool
    reason: str
    protected_surfaces: tuple[str, ...] = ()
    agency: PluginAgencyDecision | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "reason", str(self.reason))
        object.__setattr__(self, "protected_surfaces", tuple(str(item) for item in self.protected_surfaces))

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "protected_surfaces": list(self.protected_surfaces),
            "agency": self.agency.to_dict() if self.agency else None,
        }


@dataclass(frozen=True)
class PluginExecutionDecision:
    plugin_name: str
    capability: str
    allowed: bool
    effective_allowed: bool
    audit_only: bool
    reason: str
    missing_permissions: tuple[str, ...] = ()
    protected_surfaces: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "plugin_name", str(self.plugin_name))
        object.__setattr__(self, "capability", str(self.capability))
        object.__setattr__(self, "reason", str(self.reason))
        object.__setattr__(self, "missing_permissions", tuple(str(item) for item in self.missing_permissions))
        object.__setattr__(self, "protected_surfaces", tuple(str(item) for item in self.protected_surfaces))

    def to_dict(self) -> dict[str, Any]:
        return {
            "plugin_name": self.plugin_name,
            "capability": self.capability,
            "allowed": self.allowed,
            "effective_allowed": self.effective_allowed,
            "audit_only": self.audit_only,
            "reason": self.reason,
            "missing_permissions": list(self.missing_permissions),
            "protected_surfaces": list(self.protected_surfaces),
        }


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False, default=str))


def _capabilities_from_payload(value: Any) -> tuple[str, ...]:
    if isinstance(value, Mapping):
        return tuple(str(name) for name, enabled in value.items() if _truthy(enabled))
    return tuple(str(item) for item in value or ())


def _normalize_token(value: object) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _is_forbidden_capability(capability: str, forbidden: frozenset[str]) -> bool:
    normalized = _normalize_token(capability).replace(".", "_").replace(":", "_")
    return normalized in forbidden or any(normalized.endswith(f"_{item}") for item in forbidden)


def _truthy(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)
