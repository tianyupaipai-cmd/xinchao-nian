from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from ombrebrain.capabilities.catalog import register_foundation_capabilities
from ombrebrain.kernel.context import OmbreContext
from ombrebrain.kernel.errors import CapabilityLoadError, PolicyViolation
from ombrebrain.kernel.registry import CapabilityRegistry
from ombrebrain.microkernel import CapabilityMicrokernel, CapabilityRequest
from ombrebrain.plugins.contracts import (
    PluginAgencyBoundary,
    PluginExecutionDecision,
    PluginManifest,
    PluginSandboxDecision,
)


PluginHandler = Callable[[Any], Any]


_PROTECTED_SURFACES = {
    "config",
    "buckets",
    "vector database",
    "OAuth secrets",
    "deployment overrides",
}


@dataclass(frozen=True)
class PluginSandbox:
    protected_surfaces: frozenset[str] = frozenset(_PROTECTED_SURFACES)
    agency_boundary: PluginAgencyBoundary = field(default_factory=PluginAgencyBoundary.default)

    @classmethod
    def default(cls) -> "PluginSandbox":
        return cls()

    def evaluate(self, manifest: PluginManifest) -> PluginSandboxDecision:
        agency = self.agency_boundary.evaluate(manifest)
        if not agency.allowed:
            return PluginSandboxDecision(
                allowed=False,
                reason=agency.reason,
                agency=agency,
            )
        protected = tuple(surface for surface in manifest.requested_surfaces if surface in self.protected_surfaces)
        if manifest.side_effect_mode == "write_legacy_state" and protected:
            return PluginSandboxDecision(
                allowed=False,
                reason="protected surface legacy write rejected",
                protected_surfaces=protected,
                agency=agency,
            )
        return PluginSandboxDecision(allowed=True, reason="allowed", protected_surfaces=protected, agency=agency)


@dataclass
class PluginRuntime:
    sandbox: PluginSandbox
    capability_microkernel: CapabilityMicrokernel | None = None
    enforcement_mode: str = "audit"
    _plugins: dict[str, PluginManifest] = field(default_factory=dict)
    _handlers: dict[tuple[str, str], PluginHandler] = field(default_factory=dict)
    _last_execution_decision: PluginExecutionDecision | None = None

    @classmethod
    def default(cls, *, enforcement_mode: str = "audit") -> "PluginRuntime":
        return cls(
            PluginSandbox.default(),
            _foundation_microkernel(),
            _normalize_enforcement_mode(enforcement_mode),
        )

    def register(self, manifest: PluginManifest, handlers: dict[str, PluginHandler]) -> None:
        decision = self.sandbox.evaluate(manifest)
        if not decision.allowed:
            raise PermissionError(decision.reason)
        self._plugins[manifest.name] = manifest
        for capability, handler in handlers.items():
            capability_name = str(capability)
            if capability_name not in manifest.capabilities:
                raise PermissionError(f"plugin {manifest.name} did not declare capability {capability_name}")
            self._handlers[(manifest.name, capability_name)] = handler

    def execute(
        self,
        plugin_name: str,
        capability: str,
        payload: Any,
        *,
        permissions: tuple[str, ...] = (),
        actor_name: str = "plugin-runtime",
        source: str = "plugin",
    ) -> Any:
        name = str(plugin_name)
        capability_name = str(capability)
        manifest = self._plugins[name]
        if capability_name not in manifest.capabilities:
            raise PermissionError(f"plugin {name} did not declare capability {capability_name}")
        decision = self._authorize_execution(
            manifest,
            capability_name,
            payload,
            permissions=permissions,
            actor_name=actor_name,
            source=source,
        )
        self._last_execution_decision = decision
        if not decision.effective_allowed:
            raise PolicyViolation(_policy_violation_message(decision))
        try:
            handler = self._handlers[(name, capability_name)]
        except KeyError as exc:
            raise PermissionError(f"plugin {name} has no handler for {capability_name}") from exc
        return handler(payload)

    def last_execution_decision(self) -> PluginExecutionDecision | None:
        return self._last_execution_decision

    def _authorize_execution(
        self,
        manifest: PluginManifest,
        capability: str,
        payload: Any,
        *,
        permissions: tuple[str, ...],
        actor_name: str,
        source: str,
    ) -> PluginExecutionDecision:
        enforcement_mode = _normalize_enforcement_mode(self.enforcement_mode)
        audit_only = enforcement_mode == "audit"
        context = OmbreContext(
            request_id=f"plugin:{manifest.name}:{capability}",
            actor_name=actor_name,
            permissions=tuple(str(item) for item in permissions),
            source=source,
        )
        if self.capability_microkernel is None:
            return PluginExecutionDecision(
                plugin_name=manifest.name,
                capability=capability,
                allowed=True,
                effective_allowed=True,
                audit_only=audit_only,
                reason="no capability microkernel configured",
            )
        try:
            decision = self.capability_microkernel.authorize(
                CapabilityRequest(name=capability, payload=payload, context=context)
            )
        except CapabilityLoadError:
            return PluginExecutionDecision(
                plugin_name=manifest.name,
                capability=capability,
                allowed=True,
                effective_allowed=True,
                audit_only=audit_only,
                reason="plugin-local capability",
            )
        allowed = bool(decision.allowed)
        effective_allowed = True if audit_only else allowed
        return PluginExecutionDecision(
            plugin_name=manifest.name,
            capability=capability,
            allowed=allowed,
            effective_allowed=effective_allowed,
            audit_only=audit_only,
            reason="allowed" if allowed else "missing capability permissions",
            missing_permissions=decision.missing_permissions,
            protected_surfaces=decision.protected_surfaces,
        )


def _foundation_microkernel() -> CapabilityMicrokernel:
    registry = CapabilityRegistry()
    register_foundation_capabilities(registry)
    return CapabilityMicrokernel(registry)


def _normalize_enforcement_mode(value: object) -> str:
    normalized = str(value or "audit").strip().lower()
    if normalized in {"enforce", "enforced", "blocking"}:
        return "enforce"
    return "audit"


def _policy_violation_message(decision: PluginExecutionDecision) -> str:
    missing = ", ".join(decision.missing_permissions)
    suffix = f" (missing permissions: {missing})" if missing else ""
    return f"plugin policy denied {decision.plugin_name}.{decision.capability}{suffix}"
