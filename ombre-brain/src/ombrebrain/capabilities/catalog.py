from __future__ import annotations

from typing import Any

from ombrebrain.kernel.context import OmbreContext
from ombrebrain.kernel.registry import CapabilityManifest, CapabilityRegistry
from ombrebrain.version import __version__ as OMBREBRAIN_VERSION


def foundation_capabilities() -> tuple[CapabilityManifest, ...]:
    return (
        CapabilityManifest(
            name="deployment.local",
            version=OMBREBRAIN_VERSION,
            permissions=("deployment:read", "deployment:restart"),
            cluster_safe=False,
            hot_update_safe=False,
        ),
        CapabilityManifest(
            name="mcp.aggregate",
            version=OMBREBRAIN_VERSION,
            permissions=("mcp:read", "mcp:call"),
            cluster_safe=True,
            hot_update_safe=True,
        ),
        CapabilityManifest(
            name="tools.search",
            version=OMBREBRAIN_VERSION,
            permissions=("tools:search",),
            dependencies=("mcp.aggregate",),
            cluster_safe=True,
            hot_update_safe=True,
        ),
        CapabilityManifest(
            name="tools.breath",
            version=OMBREBRAIN_VERSION,
            permissions=("tools:breath", "memory:write"),
            dependencies=("tools.search",),
            writes_memory=True,
            cluster_safe=True,
            hot_update_safe=False,
        ),
        CapabilityManifest(
            name="web.dashboard",
            version=OMBREBRAIN_VERSION,
            permissions=("web:read", "web:configure"),
            dependencies=("tools.search",),
            cluster_safe=True,
            hot_update_safe=True,
        ),
        CapabilityManifest(
            name="oauth.control",
            version=OMBREBRAIN_VERSION,
            permissions=("oauth:configure",),
            dependencies=("web.dashboard",),
            cluster_safe=True,
            hot_update_safe=False,
        ),
        CapabilityManifest(
            name="hot_update.apply",
            version=OMBREBRAIN_VERSION,
            permissions=("update:plan", "update:apply"),
            dependencies=("deployment.local",),
            cluster_safe=False,
            hot_update_safe=False,
        ),
    )


def register_foundation_capabilities(registry: CapabilityRegistry) -> tuple[str, ...]:
    registered: list[str] = []
    for manifest in foundation_capabilities():
        registry.register(manifest, _handler_for(manifest))
        registered.append(manifest.name)
    return tuple(registered)


def _handler_for(manifest: CapabilityManifest):
    def handler(context: OmbreContext, payload: Any) -> dict[str, object]:
        return {
            "name": manifest.name,
            "version": manifest.version,
            "permissions": manifest.permissions,
            "dependencies": manifest.dependencies,
            "writes_memory": manifest.writes_memory,
            "cluster_safe": manifest.cluster_safe,
            "hot_update_safe": manifest.hot_update_safe,
            "request_id": context.request_id,
            "actor_name": context.actor_name,
            "payload": payload,
        }

    return handler
