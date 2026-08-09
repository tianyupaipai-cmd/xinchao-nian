from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from ombrebrain.cluster.raft.log import RaftLogEntry
from ombrebrain.cluster.raft.quorum import Quorum
from ombrebrain.cluster.replication.apply import apply_committed_event
from ombrebrain.fabric.storage.engine import MemoryFabric
from ombrebrain.kernel.errors import NotLeader, QuorumTimeout
from ombrebrain.protocol.schemas import MemoryEvent


class InMemoryRaftCluster:
    def __init__(self, node_ids: Iterable[str], root: str | Path) -> None:
        self.node_ids = tuple(str(node_id) for node_id in node_ids)
        if len(set(self.node_ids)) != len(self.node_ids):
            raise ValueError("node ids must be unique")
        if not self.node_ids:
            raise ValueError("cluster requires at least one node")

        self.root = Path(root)
        self.term = 0
        self.leader_id: str | None = None
        self._reachable = set(self.node_ids)
        self._logs: dict[str, list[RaftLogEntry]] = {node_id: [] for node_id in self.node_ids}
        self._fabrics = {node_id: MemoryFabric.open(self.root / node_id) for node_id in self.node_ids}
        self._quorum = Quorum(len(self.node_ids))

    def set_reachable(self, node_ids: Iterable[str]) -> None:
        reachable = {str(node_id) for node_id in node_ids}
        unknown = reachable.difference(self.node_ids)
        if unknown:
            joined = ", ".join(sorted(unknown))
            raise ValueError(f"Unknown node ids: {joined}")
        self._reachable = reachable

    def elect_leader(self, candidate_id: str, voters: Iterable[str] | None = None) -> bool:
        self._require_node(candidate_id)
        voter_set = self._reachable if voters is None else {str(node_id) for node_id in voters}
        voter_set = voter_set.intersection(self._reachable)
        if candidate_id not in voter_set:
            return False
        if not self._quorum.has_majority(len(voter_set)):
            return False

        self.term += 1
        self.leader_id = candidate_id
        return True

    def commit(self, event: MemoryEvent) -> RaftLogEntry:
        if self.leader_id is None:
            raise NotLeader("No leader has been elected")
        if self.leader_id not in self._reachable:
            raise QuorumTimeout(f"Leader is not reachable: {self.leader_id}")
        if not self._quorum.has_majority(len(self._reachable)):
            raise QuorumTimeout("Cannot commit without a reachable majority")

        index = len(self._logs[self.leader_id]) + 1
        committed_event = event.with_cluster_position(term=self.term, index=index)
        entry = RaftLogEntry.new(term=self.term, index=index, event=committed_event)
        for node_id in self._ordered_reachable_nodes():
            self._logs[node_id].append(entry)

        apply_committed_event(self._fabrics[self.leader_id], committed_event)
        return entry

    def log_for(self, node_id: str) -> tuple[RaftLogEntry, ...]:
        self._require_node(node_id)
        return tuple(self._logs[node_id])

    def fabric_for(self, node_id: str) -> MemoryFabric:
        self._require_node(node_id)
        return self._fabrics[node_id]

    def _ordered_reachable_nodes(self) -> tuple[str, ...]:
        return tuple(node_id for node_id in self.node_ids if node_id in self._reachable)

    def _require_node(self, node_id: str) -> None:
        if node_id not in self._logs:
            raise ValueError(f"Unknown node id: {node_id}")
