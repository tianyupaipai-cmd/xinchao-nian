from __future__ import annotations

from dataclasses import dataclass

from .commands import CommandKind, MemoryCommand


@dataclass(frozen=True)
class InvariantVerdict:
    allowed: bool
    rules: tuple[str, ...]
    reason: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "allowed": self.allowed,
            "rules": list(self.rules),
            "reason": self.reason,
        }


class MemoryInvariantSet:
    @classmethod
    def default(cls) -> "MemoryInvariantSet":
        return cls()

    def evaluate(self, command: MemoryCommand) -> InvariantVerdict:
        rules: list[str] = []
        payload = command.payload
        memory_type = str(payload.get("memory_type", "")).lower()

        if memory_type == "permanent":
            rules.append("non-decaying-permanent")

        if command.kind == CommandKind.BREATH and memory_type == "feel" and bool(payload.get("ordinary")):
            rules.append("feel-excluded-from-ordinary-breath")
            return InvariantVerdict(False, tuple(rules), "feel memory uses explicit feel surfacing")

        if memory_type == "plan":
            rules.append("plan-status-lifecycle")

        if memory_type == "letter":
            rules.append("letter-raw-preserved")

        if command.kind == CommandKind.TRACE and bool(payload.get("delete")):
            rules.append("trace-delete-removes-vector")

        return InvariantVerdict(True, tuple(rules))
