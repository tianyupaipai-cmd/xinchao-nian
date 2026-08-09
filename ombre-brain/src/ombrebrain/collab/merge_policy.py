from __future__ import annotations

from enum import Enum

from ombrebrain.protocol.schemas import MemoryEvent


class MergeDecision(Enum):
    KEEP_BOTH = "keep_both"
    PREFER_NEW = "prefer_new"
    PREFER_EXISTING = "prefer_existing"
    MARK_CONFLICT = "mark_conflict"


class MergePolicy:
    def decide(self, existing: MemoryEvent, incoming: MemoryEvent) -> MergeDecision:
        if existing.id == incoming.id:
            return MergeDecision.PREFER_EXISTING

        if _same_scope(existing, incoming) and existing.content != incoming.content:
            return MergeDecision.MARK_CONFLICT

        if bool(existing.source_chain) != bool(incoming.source_chain):
            return MergeDecision.KEEP_BOTH

        existing_position = (existing.cluster_term, existing.cluster_index)
        incoming_position = (incoming.cluster_term, incoming.cluster_index)
        if incoming_position > existing_position:
            return MergeDecision.PREFER_NEW
        if existing_position > incoming_position:
            return MergeDecision.PREFER_EXISTING

        return MergeDecision.KEEP_BOTH


def _same_scope(existing: MemoryEvent, incoming: MemoryEvent) -> bool:
    if not existing.source_chain or not incoming.source_chain:
        return False
    return (
        existing.memory_type == incoming.memory_type
        and existing.actor_name == incoming.actor_name
        and existing.source_chain == incoming.source_chain
    )
