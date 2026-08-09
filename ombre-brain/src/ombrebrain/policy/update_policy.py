from __future__ import annotations

import hashlib
import re

from ombrebrain.protocol.manifests import FileManifest, UpdateManifest, UpdatePlan


_DRIVE_ABSOLUTE = re.compile(r"^[A-Za-z]:/")
_VECTOR_SEGMENTS = {"vector", "vectors", "vector_db", "vector-db", "chroma", "qdrant", "faiss", "milvus"}
_DEPLOYMENT_ROOTS = {"deploy", "deployment"}
_OAUTH_HINTS = {"oauth", "auth"}
_SECRET_HINTS = {"secret", "token", "credential", "client_secret", "private_key"}


def evaluate_update_manifest(manifest: UpdateManifest, content_by_path: dict[str, bytes]) -> UpdatePlan:
    accepted: list[FileManifest] = []
    rejected: dict[str, str] = {}
    content = {str(path).replace("\\", "/"): value for path, value in content_by_path.items()}

    for file_manifest in manifest.files:
        reason = _rejection_reason(file_manifest, content.get(file_manifest.path))
        if reason is None:
            accepted.append(file_manifest)
        else:
            rejected[file_manifest.path] = reason

    return UpdatePlan(
        version=manifest.version,
        accepted=tuple(accepted),
        rejected=rejected,
        rollout_strategy=manifest.rollout_strategy,
        executed=False,
    )


def _rejection_reason(file_manifest: FileManifest, content: bytes | None) -> str | None:
    path = file_manifest.path
    if _is_unsafe_path(path):
        return "unsafe path"
    if _is_protected_path(path):
        return "protected path"
    if content is None:
        return "missing content"
    if len(content) != file_manifest.size:
        return "size mismatch"
    if hashlib.sha256(content).hexdigest() != file_manifest.sha256:
        return "sha256 mismatch"
    return None


def _is_unsafe_path(path: str) -> bool:
    if not path or path.startswith("/") or _DRIVE_ABSOLUTE.match(path):
        return True
    parts = path.split("/")
    return any(part in {"", ".", ".."} or ":" in part for part in parts)


def _is_protected_path(path: str) -> bool:
    parts = tuple(part.lower() for part in path.split("/"))
    filename = parts[-1]

    if filename == ".env" or filename in {"config.yaml", "config.yml"}:
        return True
    if parts[0] in {"bucket", "buckets"}:
        return True
    if _is_vector_database_path(parts):
        return True
    if _is_oauth_secret_path(parts):
        return True
    if _is_deployment_override_path(parts):
        return True
    return False


def _is_vector_database_path(parts: tuple[str, ...]) -> bool:
    if not set(parts).intersection(_VECTOR_SEGMENTS):
        return False
    return parts[0] in {"data", "db", "storage", "var", "buckets", "bucket"} or parts[-1].endswith(
        (".sqlite", ".sqlite3", ".db", ".faiss")
    )


def _is_oauth_secret_path(parts: tuple[str, ...]) -> bool:
    if not set(parts).intersection(_OAUTH_HINTS):
        return False
    joined = "/".join(parts)
    return any(hint in joined for hint in _SECRET_HINTS)


def _is_deployment_override_path(parts: tuple[str, ...]) -> bool:
    if parts[0] not in _DEPLOYMENT_ROOTS:
        return False
    filename = parts[-1]
    return ".user." in filename or filename.endswith(".user.yml") or filename.endswith(".user.yaml")
