from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ombrebrain.app.profiles import LegacyModuleRegistry, SafetyTier, build_default_legacy_profiles


class SurfaceRisk(Enum):
    PASSIVE = "passive"
    OPERATOR_UI = "operator-ui"
    MEMORY_STATE = "memory-state"
    RUNTIME_SECRET = "runtime-secret"
    DEPLOYMENT = "deployment"


@dataclass(frozen=True)
class StaticSurfaceDecision:
    path: str
    profile_module: str
    risk: SurfaceRisk
    protected: bool
    reason: str
    controls: tuple[str, ...]
    side_effects: tuple[str, ...]


class StaticSurfacePolicy:
    def __init__(self, registry: LegacyModuleRegistry):
        self.registry = registry

    @classmethod
    def default(cls) -> "StaticSurfacePolicy":
        return cls(build_default_legacy_profiles())

    def classify(self, path: str) -> StaticSurfaceDecision:
        normalized = _normalize(path)
        profile = self.registry.profile_for_path(normalized)
        protected, reason = _protected_static_reason(normalized)
        return StaticSurfaceDecision(
            path=normalized,
            profile_module=profile.module,
            risk=_risk_for(profile.module, profile.safety_tier, normalized),
            protected=protected,
            reason=reason,
            controls=tuple(profile.protected_surfaces),
            side_effects=tuple(profile.side_effects),
        )


def _risk_for(module: str, tier: SafetyTier, path: str) -> SurfaceRisk:
    if _is_runtime_secret(path):
        return SurfaceRisk.RUNTIME_SECRET
    if path.startswith(("buckets/", "bucket/")) or _looks_like_vector_db(path):
        return SurfaceRisk.MEMORY_STATE
    if tier == SafetyTier.DEPLOYMENT:
        return SurfaceRisk.DEPLOYMENT
    if module == "frontend.dashboard":
        return SurfaceRisk.OPERATOR_UI
    return SurfaceRisk.PASSIVE


def _protected_static_reason(path: str) -> tuple[bool, str]:
    if _is_runtime_secret(path):
        return True, "runtime-secret"
    if path.startswith(("buckets/", "bucket/")):
        return True, "memory-state"
    if _looks_like_vector_db(path):
        return True, "vector-database"
    if _is_deployment_user_override(path):
        return True, "deployment-user-overrides"
    return False, ""


def _is_runtime_secret(path: str) -> bool:
    filename = path.rsplit("/", 1)[-1]
    if filename in {".env", "config.yaml", "config.yml"}:
        return True
    lowered = path.lower()
    return "oauth" in lowered and any(part in lowered for part in ("secret", "token", "credential"))


def _looks_like_vector_db(path: str) -> bool:
    parts = set(path.split("/"))
    if not parts.intersection({"vector", "vectors", "vector_db", "vector-db", "chroma", "qdrant", "faiss"}):
        return False
    return path.endswith((".sqlite", ".sqlite3", ".db", ".faiss"))


def _is_deployment_user_override(path: str) -> bool:
    if not path.startswith(("deploy/", "deployment/")):
        return False
    filename = path.rsplit("/", 1)[-1]
    return ".user." in filename or filename.endswith(".user.yml") or filename.endswith(".user.yaml")


def _normalize(path: str) -> str:
    return str(path).replace("\\", "/").strip("/")
