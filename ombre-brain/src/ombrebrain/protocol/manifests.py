from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FileManifest:
    path: str
    sha256: str
    size: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", str(self.path).replace("\\", "/"))
        object.__setattr__(self, "sha256", str(self.sha256).lower())
        object.__setattr__(self, "size", int(self.size))
        if self.size < 0:
            raise ValueError("file size must be non-negative")


@dataclass(frozen=True)
class UpdateManifest:
    version: str
    files: tuple[FileManifest, ...] = field(default_factory=tuple)
    rollout_strategy: str = "single-node"

    def __post_init__(self) -> None:
        object.__setattr__(self, "version", str(self.version))
        object.__setattr__(self, "files", tuple(self.files))
        object.__setattr__(self, "rollout_strategy", str(self.rollout_strategy))


@dataclass(frozen=True)
class UpdatePlan:
    version: str
    accepted: tuple[FileManifest, ...]
    rejected: dict[str, str]
    rollout_strategy: str
    executed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "accepted", tuple(self.accepted))
        object.__setattr__(self, "rejected", dict(self.rejected))
