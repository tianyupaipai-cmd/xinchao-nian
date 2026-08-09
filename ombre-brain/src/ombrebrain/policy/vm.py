from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ombrebrain.policy.contracts import CapabilityContract, SurfaceAccessVerdict, VerdictSeverity


class PolicyOpcode(Enum):
    REQUIRE_PERMISSION = "require_permission"
    WARN_PROTECTED_SURFACE = "warn_protected_surface"
    DENY_PROTECTED_WRITE = "deny_protected_write"
    WARN_HOT_UPDATE_UNSAFE = "warn_hot_update_unsafe"
    WARN_CLUSTER_UNSAFE = "warn_cluster_unsafe"
    ALLOW = "allow"


@dataclass(frozen=True)
class PolicyInstruction:
    opcode: PolicyOpcode
    operand: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "opcode", _coerce_opcode(self.opcode))
        object.__setattr__(self, "operand", str(self.operand or ""))

    def to_dict(self) -> dict[str, str]:
        return {"opcode": self.opcode.value, "operand": self.operand}


@dataclass(frozen=True)
class PolicyProgram:
    instructions: tuple[PolicyInstruction, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "instructions", tuple(self.instructions))

    def to_dict(self) -> dict[str, object]:
        return {"instructions": [instruction.to_dict() for instruction in self.instructions]}


@dataclass(frozen=True)
class PolicyVM:
    @classmethod
    def default(cls) -> "PolicyVM":
        return cls()

    def evaluate(self, program: PolicyProgram, contract: CapabilityContract) -> SurfaceAccessVerdict:
        reasons: list[str] = []
        missing_permissions: list[str] = []
        protected_surfaces: set[str] = set()
        deny = False
        warn = False

        for instruction in program.instructions:
            operand = instruction.operand
            if instruction.opcode == PolicyOpcode.REQUIRE_PERMISSION:
                if operand and operand not in contract.permissions:
                    missing_permissions.append(operand)
                    reasons.append(f"missing permission: {operand}")
                    deny = True
            elif instruction.opcode == PolicyOpcode.WARN_PROTECTED_SURFACE:
                if operand in contract.protected_surfaces or any(access.surface == operand and access.protected for access in contract.surface_access):
                    protected_surfaces.add(operand)
                    reasons.append(f"protected surface observed: {operand}")
                    warn = True
            elif instruction.opcode == PolicyOpcode.DENY_PROTECTED_WRITE:
                for access in contract.surface_access:
                    if access.surface == operand and access.protected and access.access == "write":
                        protected_surfaces.add(operand)
                        reasons.append(f"protected surface write: {operand}")
                        deny = True
            elif instruction.opcode == PolicyOpcode.WARN_HOT_UPDATE_UNSAFE:
                if not contract.hot_update_safe:
                    reasons.append("hot-update unsafe capability")
                    warn = True
            elif instruction.opcode == PolicyOpcode.WARN_CLUSTER_UNSAFE:
                if not contract.cluster_safe:
                    reasons.append("cluster unsafe capability")
                    warn = True
            elif instruction.opcode == PolicyOpcode.ALLOW:
                continue

        severity = VerdictSeverity.DENY if deny else (VerdictSeverity.WARN if warn else VerdictSeverity.ALLOW)
        return SurfaceAccessVerdict(
            allowed=not deny,
            severity=severity,
            reasons=tuple(reasons),
            required_permissions=contract.required_permissions,
            missing_permissions=tuple(missing_permissions),
            protected_surfaces=tuple(sorted(protected_surfaces)),
            projection_surfaces=contract.projection_surfaces,
            metadata={"program": program.to_dict(), "contract_id": contract.command_id},
        )


def _coerce_opcode(value: object) -> PolicyOpcode:
    if isinstance(value, PolicyOpcode):
        return value
    return PolicyOpcode(str(value))
