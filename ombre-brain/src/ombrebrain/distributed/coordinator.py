from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ombrebrain.cluster.raft.log import RaftLogEntry
from ombrebrain.cluster.replication.catchup import CatchUpResult, catch_up_follower
from ombrebrain.distributed.membership import ClusterMembership, LeaderLease
from ombrebrain.distributed.transport import InMemoryClusterTransport
from ombrebrain.fabric.storage.engine import MemoryFabric
from ombrebrain.kernel.errors import NotLeader, QuorumTimeout
from ombrebrain.protocol.schemas import MemoryEvent


@dataclass(frozen=True)
class DistributedCommitResult:
    committed: bool
    index: int
    term: int
    leader_id: str
    acks: tuple[str, ...]


class DistributedMemoryFabricCluster:
    def __init__(self, node_ids: tuple[str, ...], root: str | Path) -> None:
        self.membership = ClusterMembership(tuple(node_ids))
        self.transport = InMemoryClusterTransport.open(self.membership.node_ids)
        self.root = Path(root)
        self.term = 0
        self._lease_epoch = 0
        self.leader_id: str | None = None
        self._logs: dict[str, list[RaftLogEntry]] = {node_id: [] for node_id in self.membership.node_ids}
        self._fabrics: dict[str, MemoryFabric] = {
            node_id: MemoryFabric.open(self.root / node_id) for node_id in self.membership.node_ids
        }

    def elect_leader(self, candidate_id: str) -> bool:
        self._require_node(candidate_id)
        reachable = self.transport.reachable_nodes()
        if candidate_id not in reachable:
            return False
        if not self.membership.with_reachable(reachable).has_majority():
            return False
        self.term += 1
        self._lease_epoch += 1
        self.leader_id = candidate_id
        return True

    def leader_lease(self) -> LeaderLease:
        leader = self.leader_id or ""
        return LeaderLease(
            leader_id=leader,
            term=self.term,
            epoch=self._lease_epoch,
            valid=bool(leader and self.transport.is_reachable(leader)),
        )

    def commit(self, event: MemoryEvent) -> DistributedCommitResult:
        if self.leader_id is None:
            raise NotLeader("No leader has been elected")
        reachable = self.transport.reachable_nodes()
        if self.leader_id not in reachable:
            raise QuorumTimeout(f"Leader is not reachable: {self.leader_id}")
        if not self.membership.with_reachable(reachable).has_majority():
            raise QuorumTimeout("Cannot commit without a reachable majority")

        index = len(self._logs[self.leader_id]) + 1
        committed = event.with_cluster_position(term=self.term, index=index)
        entry = RaftLogEntry.new(term=self.term, index=index, event=committed)
        for node_id in reachable:
            self._logs[node_id].append(entry)
            self._fabrics[node_id].append_event(committed)
        return DistributedCommitResult(
            committed=True,
            index=index,
            term=self.term,
            leader_id=self.leader_id,
            acks=reachable,
        )

    def catch_up(self, node_id: str) -> CatchUpResult:
        self._require_node(node_id)
        if self.leader_id is None:
            raise NotLeader("No leader has been elected")
        current_index = len(self._logs[node_id])
        entries = tuple(entry for entry in self._logs[self.leader_id] if entry.index > current_index)
        result = catch_up_follower(self._fabrics[node_id], current_index=current_index, entries=entries)
        self._logs[node_id].extend(entries[: result.appended_entries])
        return result

    def read_events(self, node_id: str) -> list[MemoryEvent]:
        self._require_node(node_id)
        return self._fabrics[node_id].replay_events()

    def _require_node(self, node_id: str) -> None:
        if node_id not in self._logs:
            raise ValueError(f"Unknown node id: {node_id}")
