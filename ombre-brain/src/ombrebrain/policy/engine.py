from __future__ import annotations

from dataclasses import dataclass

from ombrebrain.app.execution import ExecutionEnvelope
from ombrebrain.app.profiles import LegacyModuleProfile, LegacyModuleRegistry, build_default_legacy_profiles
from ombrebrain.domain.commands import CommandPlan, ProjectionKind
from ombrebrain.policy.contracts import CapabilityContract, SurfaceAccess
from ombrebrain.policy.vm import PolicyInstruction, PolicyOpcode, PolicyProgram, PolicyVM


@dataclass(frozen=True)
class PolicyEngine:
    registry: LegacyModuleRegistry
    vm: PolicyVM
    enforcement_mode: str = "audit"

    @classmethod
    def default(
        cls,
        registry: LegacyModuleRegistry | None = None,
        *,
        enforcement_mode: str = "audit",
    ) -> "PolicyEngine":
        return cls(
            registry or build_default_legacy_profiles(),
            PolicyVM.default(),
            _normalize_enforcement_mode(enforcement_mode),
        )

    def evaluate(self, envelope: ExecutionEnvelope, command_plan: CommandPlan) -> dict[str, object]:
        profile = self._profile_for(envelope.module)
        contract = self._contract(envelope, command_plan, profile)
        program = self._program(contract)
        verdict = self.vm.evaluate(program, contract)
        enforcement_mode = _normalize_enforcement_mode(self.enforcement_mode)
        audit_only = enforcement_mode == "audit"
        effective_allowed = True if audit_only else bool(verdict.allowed)
        return {
            **verdict.to_dict(),
            "effective_allowed": effective_allowed,
            "contract": contract.to_dict(),
            "metadata": {
                **dict(verdict.metadata),
                "program": program.to_dict(),
                "profile_module": profile.module,
                "audit_only": audit_only,
                "enforcement_mode": enforcement_mode,
                "effective_allowed": effective_allowed,
            },
        }

    def _profile_for(self, module: str) -> LegacyModuleProfile:
        normalized = str(module)
        if normalized in self.registry.names():
            return self.registry.get(normalized)
        if normalized.startswith("tools."):
            return self.registry.get("tools.*")
        if normalized.startswith("web."):
            return self.registry.get("web.*")
        if normalized.startswith("deploy."):
            return self.registry.get("deploy.*")
        root = normalized.split(".", 1)[0]
        if root in self.registry.names():
            return self.registry.get(root)
        return self.registry.get("tools.*")

    def _contract(
        self,
        envelope: ExecutionEnvelope,
        command_plan: CommandPlan,
        profile: LegacyModuleProfile,
    ) -> CapabilityContract:
        projection_surfaces = tuple(sorted({step.surface for step in command_plan.projections}))
        protected = tuple(profile.protected_surfaces)
        surface_access = tuple(
            SurfaceAccess(
                surface=surface,
                access="write" if command_plan.writes_memory else "read",
                protected=_surface_is_protected(surface, protected),
                reason="profile-protected-surface" if _surface_is_protected(surface, protected) else "",
            )
            for surface in projection_surfaces
        )
        return CapabilityContract(
            command_id=command_plan.command_id,
            command_kind=command_plan.command_kind,
            module=envelope.module,
            operation=envelope.operation,
            permissions=tuple(envelope.permissions),
            required_permissions=tuple(envelope.required_permissions or profile.permissions),
            capabilities=(envelope.capability,) if envelope.capability else (),
            side_effects=tuple(profile.side_effects),
            protected_surfaces=protected,
            writes_memory=command_plan.writes_memory or envelope.writes_memory,
            projection_surfaces=projection_surfaces,
            surface_access=surface_access,
            hot_update_safe=not any(step.kind == ProjectionKind.EXTERNAL_NETWORK for step in command_plan.projections),
            cluster_safe=not any(step.kind == ProjectionKind.DEPLOYMENT_STATE for step in command_plan.projections),
            metadata={
                "profile_module": profile.module,
                "policy_tags": list(command_plan.policy_tags),
                "behavior_contract": profile.behavior_contract,
            },
        )

    def _program(self, contract: CapabilityContract) -> PolicyProgram:
        instructions: list[PolicyInstruction] = []
        instructions.extend(PolicyInstruction(PolicyOpcode.REQUIRE_PERMISSION, permission) for permission in contract.required_permissions)
        instructions.extend(
            PolicyInstruction(PolicyOpcode.WARN_PROTECTED_SURFACE, access.surface)
            for access in contract.surface_access
            if access.protected
        )
        instructions.extend(
            PolicyInstruction(PolicyOpcode.DENY_PROTECTED_WRITE, access.surface)
            for access in contract.surface_access
            if access.protected and access.access == "write"
        )
        instructions.append(PolicyInstruction(PolicyOpcode.WARN_HOT_UPDATE_UNSAFE, "hot_update_safe"))
        instructions.append(PolicyInstruction(PolicyOpcode.WARN_CLUSTER_UNSAFE, "cluster_safe"))
        if not instructions:
            instructions.append(PolicyInstruction(PolicyOpcode.ALLOW, ""))
        return PolicyProgram(tuple(instructions))


def _surface_is_protected(surface: str, protected_surfaces: tuple[str, ...]) -> bool:
    lowered = surface.lower()
    protected = {item.lower() for item in protected_surfaces}
    if lowered in protected:
        return True
    if lowered in {"buckets", "memory_fabric"} and protected.intersection({"buckets", "bucket-volume"}):
        return True
    if lowered in {"embeddings", "vector", "vector-database"} and "vector-database" in protected:
        return True
    return False


def _normalize_enforcement_mode(value: object) -> str:
    normalized = str(value or "audit").strip().lower()
    if normalized in {"enforce", "enforced", "blocking"}:
        return "enforce"
    return "audit"
