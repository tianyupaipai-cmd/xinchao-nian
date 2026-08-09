from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from ombrebrain.kernel.context import OmbreContext


@dataclass(frozen=True)
class CapabilityRequest:
    name: str
    payload: Any
    context: OmbreContext

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", str(self.name))
        object.__setattr__(self, "payload", _json_safe(self.payload))


@dataclass(frozen=True)
class CapabilityDecision:
    name: str
    allowed: bool
    side_effect_mode: str
    missing_permissions: tuple[str, ...] = ()
    protected_surfaces: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", str(self.name))
        object.__setattr__(self, "side_effect_mode", str(self.side_effect_mode))
        object.__setattr__(self, "missing_permissions", tuple(str(item) for item in self.missing_permissions))
        object.__setattr__(self, "protected_surfaces", tuple(str(item) for item in self.protected_surfaces))

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "allowed": self.allowed,
            "side_effect_mode": self.side_effect_mode,
            "missing_permissions": list(self.missing_permissions),
            "protected_surfaces": list(self.protected_surfaces),
        }


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False, default=str))
