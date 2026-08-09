from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ombrebrain.cluster.node import NodeIdentity, NodeRole
from ombrebrain.fabric.storage.engine import MemoryFabric
from ombrebrain.kernel.errors import NotLeader
from ombrebrain.protocol.schemas import MemoryEvent


@dataclass(frozen=True)
class CommitResult:
    committed: bool
    index: int
    term: int
    leader_id: str


class ConsensusEngine(Protocol):
    def commit(self, event: MemoryEvent) -> CommitResult:
        ...


@dataclass(frozen=True)
class SingleNodeConsensus:
    node: NodeIdentity
    fabric: MemoryFabric

    def commit(self, event: MemoryEvent) -> CommitResult:
        if self.node.role != NodeRole.LEADER:
            raise NotLeader(f"Node is not leader: {self.node.node_id}")

        event = event.with_cluster_position(term=self.node.term, index=self.fabric.next_index())
        index = self.fabric.append_event(event)
        return CommitResult(
            committed=True,
            index=index,
            term=self.node.term,
            leader_id=self.node.node_id,
        )
