from __future__ import annotations


class Quorum:
    def __init__(self, node_count: int) -> None:
        if node_count < 1:
            raise ValueError("node_count must be positive")
        self.node_count = int(node_count)

    @property
    def majority(self) -> int:
        return (self.node_count // 2) + 1

    def has_majority(self, votes: int) -> bool:
        return int(votes) >= self.majority
