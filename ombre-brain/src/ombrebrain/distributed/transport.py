from __future__ import annotations

from dataclasses import dataclass


@dataclass
class InMemoryClusterTransport:
    node_ids: tuple[str, ...]
    reachable: set[str]

    @classmethod
    def open(cls, node_ids: tuple[str, ...]) -> "InMemoryClusterTransport":
        nodes = tuple(str(node_id) for node_id in node_ids)
        return cls(node_ids=nodes, reachable=set(nodes))

    def set_reachable(self, node_ids: tuple[str, ...]) -> None:
        reachable = {str(node_id) for node_id in node_ids}
        unknown = reachable.difference(self.node_ids)
        if unknown:
            raise ValueError(f"unknown reachable node ids: {', '.join(sorted(unknown))}")
        self.reachable = reachable

    def is_reachable(self, node_id: str) -> bool:
        return str(node_id) in self.reachable

    def reachable_nodes(self) -> tuple[str, ...]:
        return tuple(node_id for node_id in self.node_ids if node_id in self.reachable)
