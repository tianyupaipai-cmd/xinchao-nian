from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SafetyTier(Enum):
    PASSIVE = "passive"
    MEMORY_WRITE = "memory-write"
    FILESYSTEM_WRITE = "filesystem-write"
    NETWORK_WRITE = "network-write"
    DEPLOYMENT = "deployment"


@dataclass(frozen=True)
class LegacyModuleProfile:
    module: str
    files: tuple[str, ...]
    responsibilities: tuple[str, ...]
    side_effects: tuple[str, ...] = ()
    protected_surfaces: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    safety_tier: SafetyTier = SafetyTier.PASSIVE
    behavior_contract: str = "external-behavior-stable"


class LegacyModuleRegistry:
    def __init__(self, profiles: tuple[LegacyModuleProfile, ...] = ()):
        self._profiles: dict[str, LegacyModuleProfile] = {}
        for profile in profiles:
            self.register(profile)

    def register(self, profile: LegacyModuleProfile) -> None:
        self._profiles[profile.module] = profile

    def get(self, module: str) -> LegacyModuleProfile:
        return self._profiles[str(module)]

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._profiles))

    def all(self) -> tuple[LegacyModuleProfile, ...]:
        return tuple(self._profiles[name] for name in self.names())

    def profile_for_path(self, path: str) -> LegacyModuleProfile:
        normalized = _normalize_path(path)
        for profile in self.all():
            if any(_matches(pattern, normalized) for pattern in profile.files):
                return profile
        raise KeyError(path)


def build_default_legacy_profiles() -> LegacyModuleRegistry:
    profiles = (
        LegacyModuleProfile(
            module="decay_engine",
            files=("src/decay_engine.py",),
            responsibilities=("score-memory-vividness", "archive-low-activity-buckets"),
            side_effects=("bucket-archive-move", "embedding-backfill"),
            permissions=("memory:read", "memory:write"),
            safety_tier=SafetyTier.MEMORY_WRITE,
        ),
        LegacyModuleProfile(
            module="dehydrator",
            files=("src/dehydrator.py",),
            responsibilities=("llm-compression", "merge-analysis", "digest-extraction"),
            side_effects=("dehydration-cache-write", "external-llm-call"),
            protected_surfaces=("prompt-perspective",),
            permissions=("llm:call",),
            safety_tier=SafetyTier.NETWORK_WRITE,
        ),
        LegacyModuleProfile(
            module="embedding_engine",
            files=("src/embedding_engine.py",),
            responsibilities=("vector-generation", "semantic-search", "embedding-meta-validation"),
            side_effects=("embeddings-db-write", "external-embedding-call"),
            protected_surfaces=("vector-database",),
            permissions=("embedding:read", "embedding:write"),
            safety_tier=SafetyTier.FILESYSTEM_WRITE,
        ),
        LegacyModuleProfile(
            module="import_memory",
            files=("src/import_memory.py",),
            responsibilities=("conversation-import", "chunking", "memory-extraction"),
            side_effects=("bucket-create", "import-state-write"),
            permissions=("memory:write", "llm:call"),
            safety_tier=SafetyTier.MEMORY_WRITE,
        ),
        LegacyModuleProfile(
            module="migrate_engine",
            files=("src/migrate_engine.py",),
            responsibilities=("memory-package-import", "conflict-resolution", "reindex-planning"),
            side_effects=("bucket-file-write", "embedding-db-merge"),
            protected_surfaces=("buckets", "vector-database"),
            permissions=("memory:write", "embedding:write"),
            safety_tier=SafetyTier.FILESYSTEM_WRITE,
        ),
        LegacyModuleProfile(
            module="migration_engine",
            files=("src/migration_engine.py",),
            responsibilities=("embedding-backend-migration", "checkpoint-resume", "atomic-db-swap"),
            side_effects=("embeddings-db-backup", "migration-status-write"),
            protected_surfaces=("vector-database",),
            permissions=("embedding:write",),
            safety_tier=SafetyTier.FILESYSTEM_WRITE,
        ),
        LegacyModuleProfile(
            module="github_sync",
            files=("src/github_sync.py",),
            responsibilities=("bucket-cloud-backup", "github-restore", "batch-git-tree-commit"),
            side_effects=("network-write", "bucket-file-restore"),
            protected_surfaces=("github-token", "buckets"),
            permissions=("network:github", "memory:read"),
            safety_tier=SafetyTier.NETWORK_WRITE,
        ),
        LegacyModuleProfile(
            module="tools.*",
            files=("src/tools/*", "src/tools/**"),
            responsibilities=("mcp-tool-dispatch", "memory-tool-behavior"),
            side_effects=("memory-read", "memory-write", "webhook-fire"),
            protected_surfaces=("tool-payload-privacy",),
            permissions=("mcp:call",),
            safety_tier=SafetyTier.MEMORY_WRITE,
        ),
        LegacyModuleProfile(
            module="web.*",
            files=("src/web/*", "src/web/**"),
            responsibilities=("dashboard-api-routes", "auth", "runtime-config"),
            side_effects=("session-write", "env-config-write", "hot-update-evaluation"),
            protected_surfaces=("oauth-secrets", "dashboard-session", "config"),
            permissions=("web:route",),
            safety_tier=SafetyTier.FILESYSTEM_WRITE,
        ),
        LegacyModuleProfile(
            module="frontend.dashboard",
            files=("frontend/dashboard.html",),
            responsibilities=("dashboard-ui", "local-control-panel"),
            side_effects=("browser-api-call",),
            protected_surfaces=("oauth-toggle", "host-port-form"),
            permissions=("frontend:render",),
        ),
        LegacyModuleProfile(
            module="deploy.*",
            files=("deploy/*", "deploy/**", "render.yaml", "zbpack.json"),
            responsibilities=("self-host-deployment", "paas-entrypoints"),
            side_effects=("host-port-mapping", "container-env-mapping"),
            protected_surfaces=("deployment-user-overrides", "bucket-volume"),
            permissions=("deploy:configure",),
            safety_tier=SafetyTier.DEPLOYMENT,
        ),
        LegacyModuleProfile(
            module="dockerfile",
            files=("Dockerfile", ".dockerignore"),
            responsibilities=("container-build",),
            side_effects=("image-layer-layout",),
            protected_surfaces=("runtime-entrypoint",),
            permissions=("deploy:build",),
            safety_tier=SafetyTier.DEPLOYMENT,
        ),
        LegacyModuleProfile(
            module="config.templates",
            files=("config.example.yaml", ".env.example", "README.md", "docs/*", "docs/**"),
            responsibilities=("configuration-documentation", "operator-defaults"),
            side_effects=("docs-sync",),
            protected_surfaces=("config", "env-vars"),
            permissions=("docs:write",),
        ),
    )
    return LegacyModuleRegistry(profiles)


def _matches(pattern: str, path: str) -> bool:
    normalized = _normalize_path(pattern)
    if normalized.endswith("/**"):
        return path.startswith(normalized[:-3] + "/")
    if normalized.endswith("/*"):
        return path.startswith(normalized[:-1])
    return path == normalized


def _normalize_path(path: str) -> str:
    return str(path).replace("\\", "/").strip("/").lower()
