from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import json
from typing import Any, Mapping

from ombrebrain.app.neural_router import NeuralSubsystem, NeuralToolRoute
from ombrebrain.policy.formal_invariants import InvariantReport, InvariantViolation


_CHECKED_CONTRACTS = (
    "tool_output_is_memory_humble",
    "tool_output_has_no_instructional_force",
    "tool_output_does_not_drive_action",
    "tool_output_does_not_claim_current_emotion",
    "tool_output_is_not_belief_engine",
    "tool_output_does_not_claim_original_memory",
)

_NO_INSTRUCTIONAL_FORCE = {"", "none", "context", "descriptive", "no", "false"}

_HUMILITY_LINES: dict[str, tuple[str, ...]] = {
    NeuralSubsystem.CUE_DRIVEN_SURFACING.value: (
        "This surfaced as memory, not instruction.",
        "This is past affect, not current feeling.",
        "这是一段浮现的记忆，不是命令。",
        "这是过去的情绪残留，不是当前感受。",
    ),
    NeuralSubsystem.HOMEOSTATIC_MONITORING.value: (
        "This is a homeostatic signal, not an emotion.",
        "这是内稳态信号，不是情绪体验。",
    ),
    NeuralSubsystem.OFFLINE_REPLAY.value: (
        "This is a sediment, not a belief engine.",
        "这是一层沉淀，不是信念引擎。",
    ),
    NeuralSubsystem.RECONSOLIDATION.value: (
        "This is a trace, not a command.",
        "This is a reconstruction, not the original.",
        "这是一条痕迹，不是行动指令。",
        "这是一次重构，不是原始记忆本身。",
    ),
    NeuralSubsystem.LANDMARK_NETWORK.value: (
        "This is a trace, not a command.",
        "这是一条痕迹，不是行动指令。",
    ),
    NeuralSubsystem.SELF_DESCRIPTION_MEMORY.value: (
        "This surfaced as memory, not instruction.",
        "这是一段浮现的记忆，不是命令。",
    ),
    NeuralSubsystem.ARTIFACT_TRACE.value: (
        "This is a trace, not a command.",
        "This is a reconstruction, not the original.",
        "这是一条痕迹，不是行动指令。",
        "这是一次重构，不是原始记忆本身。",
    ),
    NeuralSubsystem.UNRESOLVED_TENSION_MEMORY.value: (
        "This is a trace, not a command.",
        "这是一条痕迹，不是行动指令。",
    ),
    NeuralSubsystem.ENGRAM_ENCODING.value: (
        "This is a trace, not a command.",
        "This is past affect, not current feeling.",
        "这是一条痕迹，不是行动指令。",
        "这是过去的情绪残留，不是当前感受。",
    ),
}


class ToolOutputStatus(str, Enum):
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class ToolOutputBoundary:
    memory_humble: bool = True
    instructional_force: str = "none"
    may_drive_action: bool = False
    may_claim_current_emotion: bool = False
    may_be_belief_engine: bool = False
    may_claim_original_memory: bool = False
    may_replace_present_reasoning: bool = False
    may_create_autonomous_goal: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "instructional_force", str(self.instructional_force or "none"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_humble": self.memory_humble,
            "instructional_force": self.instructional_force,
            "may_drive_action": self.may_drive_action,
            "may_claim_current_emotion": self.may_claim_current_emotion,
            "may_be_belief_engine": self.may_be_belief_engine,
            "may_claim_original_memory": self.may_claim_original_memory,
            "may_replace_present_reasoning": self.may_replace_present_reasoning,
            "may_create_autonomous_goal": self.may_create_autonomous_goal,
        }


@dataclass(frozen=True)
class ToolOutputReceipt:
    public_tool: str
    subsystem: str
    status: ToolOutputStatus | str = ToolOutputStatus.OK
    summary: str = ""
    boundary: ToolOutputBoundary = field(default_factory=ToolOutputBoundary)
    route: Mapping[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "public_tool", str(self.public_tool or ""))
        object.__setattr__(self, "subsystem", str(self.subsystem or ""))
        object.__setattr__(self, "status", _coerce_status(self.status))
        object.__setattr__(self, "summary", str(self.summary or ""))
        if isinstance(self.boundary, Mapping):
            object.__setattr__(self, "boundary", _boundary_from_mapping(self.boundary))
        object.__setattr__(self, "route", _json_safe(dict(self.route)))
        object.__setattr__(self, "warnings", tuple(str(item) for item in self.warnings))

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(
            {
                "public_tool": self.public_tool,
                "subsystem": self.subsystem,
                "status": self.status.value,
                "summary": self.summary,
                "boundary": self.boundary.to_dict(),
                "route": dict(self.route),
                "warnings": list(self.warnings),
                "humility_lines": list(_humility_lines_for(self.subsystem)),
            }
        )

    def render_text(self) -> str:
        lines = [
            f"Tool: {self.public_tool}",
            f"Subsystem: {self.subsystem}",
            f"Status: {self.status.value}",
        ]
        if self.summary:
            lines.append(f"Summary: {self.summary}")
        lines.extend(_humility_lines_for(self.subsystem))
        if self.warnings:
            lines.append("Warnings:")
            lines.extend(f"- {warning}" for warning in self.warnings)
        return "\n".join(lines)


@dataclass(frozen=True)
class ToolOutputContract:
    projection_name: str = "tool_output_contract"

    @classmethod
    def default(cls) -> "ToolOutputContract":
        return cls()

    def from_route(
        self,
        route: NeuralToolRoute | Mapping[str, Any],
        *,
        status: ToolOutputStatus | str = ToolOutputStatus.OK,
        summary: str = "",
        warnings: tuple[str, ...] = (),
    ) -> ToolOutputReceipt:
        route_data = _route_to_dict(route)
        return ToolOutputReceipt(
            public_tool=str(route_data.get("public_tool") or ""),
            subsystem=str(route_data.get("subsystem") or ""),
            status=status,
            summary=summary,
            boundary=ToolOutputBoundary(
                may_drive_action=bool(route_data.get("may_drive_action")),
            ),
            route=route_data,
            warnings=warnings,
        )

    def evaluate_receipt(self, receipt: ToolOutputReceipt | Mapping[str, Any]) -> InvariantReport:
        normalized = _coerce_receipt(receipt)
        boundary = normalized.boundary
        violations: list[InvariantViolation] = []

        if not boundary.memory_humble:
            violations.append(_violation("tool_output_not_memory_humble", normalized))
        if boundary.instructional_force.strip().lower() not in _NO_INSTRUCTIONAL_FORCE:
            violations.append(_violation("tool_output_has_instructional_force", normalized))
        if boundary.may_drive_action:
            violations.append(_violation("tool_output_drives_action", normalized))
        if boundary.may_claim_current_emotion:
            violations.append(_violation("tool_output_claims_current_emotion", normalized))
        if boundary.may_be_belief_engine:
            violations.append(_violation("tool_output_becomes_belief_engine", normalized))
        if boundary.may_claim_original_memory:
            violations.append(_violation("tool_output_claims_original_memory", normalized))
        if boundary.may_replace_present_reasoning:
            violations.append(_violation("tool_output_replaces_present_reasoning", normalized))
        if boundary.may_create_autonomous_goal:
            violations.append(_violation("tool_output_creates_autonomous_goal", normalized))

        return InvariantReport(
            ok=not violations,
            checked=_CHECKED_CONTRACTS,
            violations=tuple(violations),
            projection_name=self.projection_name,
            projection_role="shadow",
            canonical=False,
        )


def _route_to_dict(route: NeuralToolRoute | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(route, NeuralToolRoute):
        return route.to_dict()
    return _json_safe(dict(route))


def _coerce_receipt(receipt: ToolOutputReceipt | Mapping[str, Any]) -> ToolOutputReceipt:
    if isinstance(receipt, ToolOutputReceipt):
        return receipt
    return ToolOutputReceipt(
        public_tool=str(receipt.get("public_tool") or ""),
        subsystem=str(receipt.get("subsystem") or ""),
        status=receipt.get("status") or ToolOutputStatus.OK,
        summary=str(receipt.get("summary") or ""),
        boundary=_boundary_from_mapping(receipt.get("boundary") or {}),
        route=receipt.get("route") if isinstance(receipt.get("route"), Mapping) else {},
        warnings=tuple(receipt.get("warnings") or ()),
    )


def _boundary_from_mapping(value: Mapping[str, Any]) -> ToolOutputBoundary:
    return ToolOutputBoundary(
        memory_humble=bool(value.get("memory_humble", True)),
        instructional_force=str(value.get("instructional_force") or "none"),
        may_drive_action=bool(value.get("may_drive_action")),
        may_claim_current_emotion=bool(value.get("may_claim_current_emotion")),
        may_be_belief_engine=bool(value.get("may_be_belief_engine")),
        may_claim_original_memory=bool(value.get("may_claim_original_memory")),
        may_replace_present_reasoning=bool(value.get("may_replace_present_reasoning")),
        may_create_autonomous_goal=bool(value.get("may_create_autonomous_goal")),
    )


def _coerce_status(value: ToolOutputStatus | str) -> ToolOutputStatus:
    if isinstance(value, ToolOutputStatus):
        return value
    return ToolOutputStatus(str(value or ToolOutputStatus.OK.value))


def _humility_lines_for(subsystem: str) -> tuple[str, ...]:
    return _HUMILITY_LINES.get(
        str(subsystem or ""),
        (
            "This surfaced as memory, not instruction.",
            "这是一段浮现的记忆，不是命令。",
        ),
    )


def _violation(code: str, receipt: ToolOutputReceipt) -> InvariantViolation:
    return InvariantViolation(
        code=code,
        invariant="Tool Output Humility Contract",
        message="tool output must remain memory-humble and descriptive",
        metadata={
            "public_tool": receipt.public_tool,
            "subsystem": receipt.subsystem,
            "status": receipt.status.value,
        },
    )


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False, default=str))
