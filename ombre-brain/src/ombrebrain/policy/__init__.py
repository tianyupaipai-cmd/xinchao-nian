from .update_policy import evaluate_update_manifest

__all__ = [
    "CapabilityContract",
    "PolicyEngine",
    "PolicyInstruction",
    "PolicyOpcode",
    "PolicyProgram",
    "PolicyVM",
    "RedLineContract",
    "RedLineFeatureSpec",
    "RedLineReport",
    "RedLineViolation",
    "SurfaceDecision",
    "SurfaceMode",
    "SurfacePolicyVM",
    "StaticSurfacePolicy",
    "SurfaceAccess",
    "SurfaceAccessVerdict",
    "SurfaceRisk",
    "FormalInvariantChecker",
    "InvariantReport",
    "InvariantViolation",
    "VerdictSeverity",
    "evaluate_update_manifest",
]


def __getattr__(name: str):
    if name in {"StaticSurfacePolicy", "SurfaceRisk"}:
        from .static_surfaces import StaticSurfacePolicy, SurfaceRisk

        return {"StaticSurfacePolicy": StaticSurfacePolicy, "SurfaceRisk": SurfaceRisk}[name]
    if name in {"SurfaceDecision", "SurfaceMode", "SurfacePolicyVM"}:
        from .surfacing import SurfaceDecision, SurfaceMode, SurfacePolicyVM

        return {
            "SurfaceDecision": SurfaceDecision,
            "SurfaceMode": SurfaceMode,
            "SurfacePolicyVM": SurfacePolicyVM,
        }[name]
    if name in {"RedLineContract", "RedLineFeatureSpec", "RedLineReport", "RedLineViolation"}:
        from .red_lines import RedLineContract, RedLineFeatureSpec, RedLineReport, RedLineViolation

        return {
            "RedLineContract": RedLineContract,
            "RedLineFeatureSpec": RedLineFeatureSpec,
            "RedLineReport": RedLineReport,
            "RedLineViolation": RedLineViolation,
        }[name]
    if name in {"FormalInvariantChecker", "InvariantReport", "InvariantViolation"}:
        from .formal_invariants import FormalInvariantChecker, InvariantReport, InvariantViolation

        return {
            "FormalInvariantChecker": FormalInvariantChecker,
            "InvariantReport": InvariantReport,
            "InvariantViolation": InvariantViolation,
        }[name]
    if name in {"CapabilityContract", "SurfaceAccess", "SurfaceAccessVerdict", "VerdictSeverity"}:
        from .contracts import CapabilityContract, SurfaceAccess, SurfaceAccessVerdict, VerdictSeverity

        return {
            "CapabilityContract": CapabilityContract,
            "SurfaceAccess": SurfaceAccess,
            "SurfaceAccessVerdict": SurfaceAccessVerdict,
            "VerdictSeverity": VerdictSeverity,
        }[name]
    if name == "PolicyEngine":
        from .engine import PolicyEngine

        return PolicyEngine
    if name in {"PolicyInstruction", "PolicyOpcode", "PolicyProgram", "PolicyVM"}:
        from .vm import PolicyInstruction, PolicyOpcode, PolicyProgram, PolicyVM

        return {
            "PolicyInstruction": PolicyInstruction,
            "PolicyOpcode": PolicyOpcode,
            "PolicyProgram": PolicyProgram,
            "PolicyVM": PolicyVM,
        }[name]
    raise AttributeError(name)
