from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .context import OmbreContext
from .errors import CapabilityLoadError, PolicyViolation


CapabilityHandler = Callable[[OmbreContext, object], object]


@dataclass(frozen=True)
class CapabilityManifest:
    name: str
    version: str
    permissions: tuple[str, ...] = field(default_factory=tuple)
    dependencies: tuple[str, ...] = field(default_factory=tuple)
    writes_memory: bool = False
    cluster_safe: bool = False
    hot_update_safe: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "permissions", tuple(self.permissions))
        object.__setattr__(self, "dependencies", tuple(self.dependencies))


@dataclass(frozen=True)
class RegisteredCapability:
    manifest: CapabilityManifest
    handler: CapabilityHandler


class CapabilityRegistry:
    def __init__(self) -> None:
        self._capabilities: dict[str, RegisteredCapability] = {}

    def register(self, manifest: CapabilityManifest, handler: CapabilityHandler) -> RegisteredCapability:
        if manifest.name in self._capabilities:
            raise CapabilityLoadError(f"Capability already registered: {manifest.name}")

        missing = tuple(name for name in manifest.dependencies if name not in self._capabilities)
        if missing:
            joined = ", ".join(missing)
            raise CapabilityLoadError(f"Capability {manifest.name} has missing dependencies: {joined}")

        capability = RegisteredCapability(manifest=manifest, handler=handler)
        self._capabilities[manifest.name] = capability
        return capability

    def get(self, name: str) -> RegisteredCapability:
        try:
            return self._capabilities[name]
        except KeyError as exc:
            raise CapabilityLoadError(f"Capability is not registered: {name}") from exc

    def dispatch(self, name: str, context: OmbreContext, payload: Any) -> object:
        capability = self.get(name)
        missing = tuple(
            permission for permission in capability.manifest.permissions if not context.has_permission(permission)
        )
        if missing:
            joined = ", ".join(missing)
            raise PolicyViolation(f"Capability {name} requires permissions: {joined}")
        return capability.handler(context, payload)

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._capabilities))
