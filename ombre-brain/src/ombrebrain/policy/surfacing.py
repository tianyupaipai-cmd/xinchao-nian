from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Mapping, Any


class SurfaceMode(str, Enum):
    SPONTANEOUS = "spontaneous"
    SEARCH = "search"
    IMPORTANCE = "importance"
    DREAM = "dream"


@dataclass(frozen=True)
class SurfaceDecision:
    allowed: bool
    mode: str
    bucket_id: str
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "allowed": self.allowed,
            "mode": self.mode,
            "bucket_id": self.bucket_id,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class SurfacePolicyVM:
    """Deterministic read-side policy for memory surfacing.

    This is deliberately small for Phase 3: Markdown buckets remain canonical,
    and the VM only decides whether a bucket may enter a specific read pool.
    """

    private_types: tuple[str, ...] = ("feel", "plan", "letter", "self", "i")

    @classmethod
    def default(cls) -> "SurfacePolicyVM":
        return cls()

    def evaluate_bucket(self, bucket: Mapping[str, Any] | None, mode: str | SurfaceMode) -> SurfaceDecision:
        normalized_mode = _coerce_mode(mode)
        if not bucket:
            return SurfaceDecision(
                allowed=False,
                mode=normalized_mode.value,
                bucket_id="",
                reasons=("missing_bucket",),
            )

        metadata = bucket.get("metadata") or {}
        if not isinstance(metadata, Mapping):
            metadata = {}
        bucket_id = str(bucket.get("id") or metadata.get("id") or "")
        bucket_type = _metadata_type(metadata)
        reasons: list[str] = []

        if bucket_type == "tombstone" or _truthy(metadata.get("tombstone")):
            reasons.append("tombstone")
        if bucket_type == "archived":
            reasons.append("archived")
        if metadata.get("deleted_at"):
            reasons.append("deleted")

        if normalized_mode in (SurfaceMode.SPONTANEOUS, SurfaceMode.DREAM):
            if _truthy(metadata.get("dont_surface")):
                reasons.append("dont_surface")
            if _truthy(metadata.get("anchor")):
                reasons.append("anchor")
            if bucket_type in self.private_types:
                reasons.append("private_type")
        elif normalized_mode == SurfaceMode.IMPORTANCE:
            if _truthy(metadata.get("dont_surface")):
                reasons.append("dont_surface")
            if bucket_type in self.private_types:
                reasons.append("private_type")

        return SurfaceDecision(
            allowed=not reasons,
            mode=normalized_mode.value,
            bucket_id=bucket_id,
            reasons=tuple(reasons),
        )

    def filter_buckets(
        self,
        buckets: Iterable[Mapping[str, Any]],
        mode: str | SurfaceMode,
    ) -> list[Mapping[str, Any]]:
        return [bucket for bucket in buckets if self.evaluate_bucket(bucket, mode).allowed]


def _coerce_mode(mode: str | SurfaceMode) -> SurfaceMode:
    if isinstance(mode, SurfaceMode):
        return mode
    try:
        return SurfaceMode(str(mode or SurfaceMode.SPONTANEOUS.value).lower())
    except ValueError:
        return SurfaceMode.SPONTANEOUS


def _metadata_type(metadata: Mapping[str, Any]) -> str:
    return str(metadata.get("type") or "dynamic").strip().lower()


def _truthy(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)
