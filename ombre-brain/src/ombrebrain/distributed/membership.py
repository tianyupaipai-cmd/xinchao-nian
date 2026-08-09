from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ClusterMembership:
    node_ids: tuple[str, ...]
    reachable: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        nodes = tuple(str(node_id) for node_id in self.node_ids)
        if not nodes:
            raise ValueError("cluster requires at least one node")
        if len(set(nodes)) != len(nodes):
            raise ValueError("node ids must be unique")
        reachable = tuple(str(node_id) for node_id in (self.reachable or nodes))
        unknown = set(reachable).difference(nodes)
        if unknown:
            raise ValueError(f"unknown reachable node ids: {', '.join(sorted(unknown))}")
        object.__setattr__(self, "node_ids", nodes)
        object.__setattr__(self, "reachable", reachable)

    @property
    def majority(self) -> int:
        return len(self.node_ids) // 2 + 1

    def has_majority(self) -> bool:
        return len(set(self.reachable)) >= self.majority

    def with_reachable(self, node_ids: tuple[str, ...]) -> "ClusterMembership":
        return ClusterMembership(self.node_ids, tuple(node_ids))


@dataclass(frozen=True)
class LeaderLease:
    leader_id: str
    term: int
    epoch: int
    valid: bool
