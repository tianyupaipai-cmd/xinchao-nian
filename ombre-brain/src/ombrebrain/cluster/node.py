from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class NodeRole(Enum):
    LEADER = "leader"
    FOLLOWER = "follower"
    CANDIDATE = "candidate"


@dataclass(frozen=True)
class NodeIdentity:
    node_id: str
    address: str
    role: NodeRole = NodeRole.FOLLOWER
    term: int = 1
