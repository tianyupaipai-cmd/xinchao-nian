from __future__ import annotations

from dataclasses import dataclass

from ombrebrain.kernel.errors import PolicyViolation
from ombrebrain.kernel.registry import CapabilityRegistry
from ombrebrain.microkernel.contracts import CapabilityDecision, CapabilityRequest


@dataclass(frozen=True)
class CapabilityMicrokernel:
    registry: CapabilityRegistry

    def authorize(self, request: CapabilityRequest) -> CapabilityDecision:
        capability = self.registry.get(request.name)
        manifest = capability.manifest
        missing = tuple(
            permission for permission in manifest.permissions if not request.context.has_permission(permission)
        )
        return CapabilityDecision(
            name=manifest.name,
            allowed=not missing,
            side_effect_mode=_side_effect_mode(manifest.writes_memory),
            missing_permissions=missing,
            protected_surfaces=_protected_surfaces(manifest.name, manifest.writes_memory),
        )

    def dispatch(self, request: CapabilityRequest) -> object:
        decision = self.authorize(request)
        if not decision.allowed:
            joined = ", ".join(decision.missing_permissions)
            raise PolicyViolation(f"Capability {request.name} requires permissions: {joined}")
        return self.registry.dispatch(request.name, request.context, request.payload)


def _side_effect_mode(writes_memory: bool) -> str:
    return "write_side_channel" if writes_memory else "read_only"


def _protected_surfaces(name: str, writes_memory: bool) -> tuple[str, ...]:
    surfaces: list[str] = []
    if writes_memory:
        surfaces.extend(("buckets", "memory_fabric"))
    if name.startswith("oauth."):
        surfaces.append("OAuth secrets")
    if name.startswith("hot_update."):
        surfaces.extend(("config", "buckets", "vector database", "deployment overrides"))
    if name.startswith("web."):
        surfaces.append("Dashboard existing routes")
    return tuple(surfaces)
