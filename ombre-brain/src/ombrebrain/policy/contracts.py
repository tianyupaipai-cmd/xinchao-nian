from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import json
from typing import Any

from ombrebrain.domain.commands import CommandKind


class VerdictSeverity(Enum):
    ALLOW = "allow"
    WARN = "warn"
    DENY = "deny"


@dataclass(frozen=True)
class SurfaceAccess:
    surface: str
    access: str
    protected: bool = False
    reason: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "surface", str(self.surface))
        object.__setattr__(self, "access", str(self.access))
        object.__setattr__(self, "protected", bool(self.protected))
        object.__setattr__(self, "reason", str(self.reason or ""))

    def to_dict(self) -> dict[str, object]:
        return {
            "surface": self.surface,
            "access": self.access,
            "protected": self.protected,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class CapabilityContract:
    command_id: str
    command_kind: CommandKind
    module: str
    operation: str
    permissions: tuple[str, ...] = ()
    required_permissions: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    side_effects: tuple[str, ...] = ()
    protected_surfaces: tuple[str, ...] = ()
    writes_memory: bool = False
    projection_surfaces: tuple[str, ...] = ()
    surface_access: tuple[SurfaceAccess, ...] = ()
    hot_update_safe: bool = True
    cluster_safe: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "command_id", str(self.command_id))
        object.__setattr__(self, "command_kind", _coerce_command_kind(self.command_kind))
        object.__setattr__(self, "module", str(self.module))
        object.__setattr__(self, "operation", str(self.operation))
        object.__setattr__(self, "permissions", _string_tuple(self.permissions))
        object.__setattr__(self, "required_permissions", _string_tuple(self.required_permissions))
        object.__setattr__(self, "capabilities", _string_tuple(self.capabilities))
        object.__setattr__(self, "side_effects", _string_tuple(self.side_effects))
        object.__setattr__(self, "protected_surfaces", _string_tuple(self.protected_surfaces))
        object.__setattr__(self, "writes_memory", bool(self.writes_memory))
        object.__setattr__(self, "projection_surfaces", _string_tuple(self.projection_surfaces))
        object.__setattr__(self, "surface_access", tuple(self.surface_access))
        object.__setattr__(self, "hot_update_safe", bool(self.hot_update_safe))
        object.__setattr__(self, "cluster_safe", bool(self.cluster_safe))
        object.__setattr__(self, "metadata", _json_safe(self.metadata))

    def to_dict(self) -> dict[str, object]:
        return {
            "command_id": self.command_id,
            "command_kind": self.command_kind.value,
            "module": self.module,
            "operation": self.operation,
            "permissions": list(self.permissions),
            "required_permissions": list(self.required_permissions),
            "capabilities": list(self.capabilities),
            "side_effects": list(self.side_effects),
            "protected_surfaces": list(self.protected_surfaces),
            "writes_memory": self.writes_memory,
            "projection_surfaces": list(self.projection_surfaces),
            "surface_access": [access.to_dict() for access in self.surface_access],
            "hot_update_safe": self.hot_update_safe,
            "cluster_safe": self.cluster_safe,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class SurfaceAccessVerdict:
    allowed: bool
    severity: VerdictSeverity = VerdictSeverity.ALLOW
    reasons: tuple[str, ...] = ()
    required_permissions: tuple[str, ...] = ()
    missing_permissions: tuple[str, ...] = ()
    protected_surfaces: tuple[str, ...] = ()
    projection_surfaces: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "allowed", bool(self.allowed))
        object.__setattr__(self, "severity", _coerce_severity(self.severity))
        object.__setattr__(self, "reasons", _string_tuple(self.reasons))
        object.__setattr__(self, "required_permissions", _string_tuple(self.required_permissions))
        object.__setattr__(self, "missing_permissions", _string_tuple(self.missing_permissions))
        object.__setattr__(self, "protected_surfaces", _string_tuple(self.protected_surfaces))
        object.__setattr__(self, "projection_surfaces", _string_tuple(self.projection_surfaces))
        object.__setattr__(self, "metadata", _json_safe(self.metadata))

    def to_dict(self) -> dict[str, object]:
        return {
            "allowed": self.allowed,
            "severity": self.severity.value,
            "reasons": list(self.reasons),
            "required_permissions": list(self.required_permissions),
            "missing_permissions": list(self.missing_permissions),
            "protected_surfaces": list(self.protected_surfaces),
            "projection_surfaces": list(self.projection_surfaces),
            "metadata": dict(self.metadata),
        }


def _coerce_command_kind(value: object) -> CommandKind:
    if isinstance(value, CommandKind):
        return value
    return CommandKind(str(value))


def _coerce_severity(value: object) -> VerdictSeverity:
    if isinstance(value, VerdictSeverity):
        return value
    return VerdictSeverity(str(value))


def _string_tuple(value: tuple[str, ...] | list[str] | object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (tuple, list, set)):
        return tuple(str(item) for item in value)
    return (str(value),)


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False, default=str))
