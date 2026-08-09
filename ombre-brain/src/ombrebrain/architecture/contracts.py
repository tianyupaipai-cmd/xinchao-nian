from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import json
from typing import Any


class SideEffectMode(Enum):
    READ_ONLY = "read_only"
    AUDIT_ONLY = "audit_only"
    WRITE_SIDE_CHANNEL = "write_side_channel"
    WRITE_LEGACY_STATE = "write_legacy_state"
    EXTERNAL_IO = "external_io"


@dataclass(frozen=True)
class ComponentDescriptor:
    name: str
    layer: str
    side_effect_mode: SideEffectMode
    owns_surfaces: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    critical: bool = False
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", str(self.name))
        object.__setattr__(self, "layer", str(self.layer))
        object.__setattr__(self, "side_effect_mode", _coerce_mode(self.side_effect_mode))
        object.__setattr__(self, "owns_surfaces", tuple(str(item) for item in self.owns_surfaces))
        object.__setattr__(self, "dependencies", tuple(str(item) for item in self.dependencies))
        object.__setattr__(self, "notes", str(self.notes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "layer": self.layer,
            "side_effect_mode": self.side_effect_mode.value,
            "owns_surfaces": list(self.owns_surfaces),
            "dependencies": list(self.dependencies),
            "critical": self.critical,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class ComponentGraph:
    components: tuple[ComponentDescriptor, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "components", tuple(self.components))

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(component.name for component in self.components)

    def by_name(self) -> dict[str, ComponentDescriptor]:
        return {component.name: component for component in self.components}

    def to_dict(self) -> dict[str, Any]:
        return {"components": [component.to_dict() for component in self.components]}


@dataclass(frozen=True)
class ArchitectureIssue:
    code: str
    message: str
    component: str = ""
    surface: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", str(self.code))
        object.__setattr__(self, "message", str(self.message))
        object.__setattr__(self, "component", str(self.component))
        object.__setattr__(self, "surface", str(self.surface))
        object.__setattr__(self, "metadata", _json_safe(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "component": self.component,
            "surface": self.surface,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ArchitectureReport:
    ok: bool
    components: tuple[str, ...]
    issues: tuple[ArchitectureIssue, ...]

    @property
    def issue_count(self) -> int:
        return len(self.issues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "components": list(self.components),
            "issue_count": self.issue_count,
            "issues": [issue.to_dict() for issue in self.issues],
        }


def _coerce_mode(value: SideEffectMode | str) -> SideEffectMode:
    if isinstance(value, SideEffectMode):
        return value
    return SideEffectMode(str(value))


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False, default=str))
