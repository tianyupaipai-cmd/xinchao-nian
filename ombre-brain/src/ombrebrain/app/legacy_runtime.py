from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from ombrebrain.app.command_boundary_health import build_runtime_command_boundary_health
from ombrebrain.app.command_bridge import LegacyCommandBridge
from ombrebrain.app.execution import ExecutionEnvelope, ExecutionOutcome, LegacyExecutionPipeline
from ombrebrain.app.neural_router import NeuralToolRouter, ToolScope
from ombrebrain.app.profiles import LegacyModuleRegistry, build_default_legacy_profiles
from ombrebrain.app.tool_output_contract import ToolOutputContract, ToolOutputStatus
from ombrebrain.capabilities.catalog import register_foundation_capabilities
from ombrebrain.decision.debug import DecisionDebugService
from ombrebrain.decision.ledger import DecisionLedger
from ombrebrain.domain import AdvancedCommandBoundaryContract, BoundaryStage, CommandBoundaryReceipt
from ombrebrain.eventsourcing.kernel import EventSourcedMemoryKernel
from ombrebrain.fabric.storage.engine import MemoryFabric
from ombrebrain.kernel.context import OmbreContext
from ombrebrain.kernel.registry import CapabilityRegistry
from ombrebrain.microkernel import CapabilityMicrokernel, CapabilityRequest
from ombrebrain.policy.static_surfaces import StaticSurfacePolicy
from ombrebrain.policy.update_policy import evaluate_update_manifest
from ombrebrain.policy.engine import PolicyEngine
from ombrebrain.policy.formal_invariants import FormalInvariantChecker
from ombrebrain.projection.auditor import ConsistencyAuditor
from ombrebrain.projection.audit_runtime import ProjectionAuditRuntime
from ombrebrain.projection.runtime import ProjectionRuntime
from ombrebrain.protocol.schemas import ActorKind, MemoryEvent, MemoryType, Visibility
from ombrebrain.retrieval import PolicyGatedRetrievalScorer, QueryPlanner, RetrievalEngine, SurfaceContextCompiler


@dataclass(frozen=True)
class LegacyRuntime:
    root: Path
    fabric: MemoryFabric
    registry: CapabilityRegistry
    config_snapshot: dict[str, object]
    module_profiles: LegacyModuleRegistry
    static_surface_policy: StaticSurfacePolicy
    command_bridge: LegacyCommandBridge
    projection_runtime: ProjectionRuntime
    consistency_auditor: ConsistencyAuditor
    projection_audit_runtime: ProjectionAuditRuntime
    policy_engine: PolicyEngine
    decision_ledger: DecisionLedger
    event_sourced_kernel: EventSourcedMemoryKernel
    query_planner: QueryPlanner
    retrieval_engine: RetrievalEngine
    retrieval_scorer: PolicyGatedRetrievalScorer
    capability_microkernel: CapabilityMicrokernel
    neural_tool_router: NeuralToolRouter
    tool_output_contract: ToolOutputContract

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "LegacyRuntime":
        buckets_dir = Path(str(config.get("buckets_dir") or "buckets"))
        root = buckets_dir / ".ombrebrain-v3"
        registry = CapabilityRegistry()
        register_foundation_capabilities(registry)
        runtime_registry = registry
        return cls(
            root=root,
            fabric=MemoryFabric.open(root),
            registry=runtime_registry,
            config_snapshot=_json_safe(config),
            module_profiles=build_default_legacy_profiles(),
            static_surface_policy=StaticSurfacePolicy.default(),
            command_bridge=LegacyCommandBridge.default(),
            projection_runtime=ProjectionRuntime.default(),
            consistency_auditor=ConsistencyAuditor.default(),
            projection_audit_runtime=ProjectionAuditRuntime.default(config_snapshot=_json_safe(config)),
            policy_engine=PolicyEngine.default(
                build_default_legacy_profiles(),
                enforcement_mode=_policy_enforcement_mode(config),
            ),
            decision_ledger=DecisionLedger.default(),
            event_sourced_kernel=EventSourcedMemoryKernel.default(),
            query_planner=QueryPlanner.default(),
            retrieval_engine=RetrievalEngine.default(),
            retrieval_scorer=PolicyGatedRetrievalScorer.default(),
            capability_microkernel=CapabilityMicrokernel(runtime_registry),
            neural_tool_router=NeuralToolRouter.default(),
            tool_output_contract=ToolOutputContract.default(),
        )

    @property
    def execution_pipeline(self) -> LegacyExecutionPipeline:
        return LegacyExecutionPipeline(self)

    def capability_names(self) -> tuple[str, ...]:
        return self.registry.names()

    def context(
        self,
        *,
        actor_name: str,
        source: str,
        permissions: tuple[str, ...],
    ) -> OmbreContext:
        return OmbreContext(
            request_id=f"legacy:{source}:{actor_name}",
            actor_name=actor_name,
            permissions=permissions,
            source=source,
            config_snapshot=self.config_snapshot,
        )

    def dispatch_capability(
        self,
        name: str,
        payload: object,
        *,
        permissions: tuple[str, ...],
        actor_name: str,
        source: str,
    ) -> object:
        return self.capability_microkernel.dispatch(
            CapabilityRequest(
                name=name,
                payload=payload,
                context=self.context(actor_name=actor_name, source=source, permissions=permissions),
            )
        )

    def record_bucket_event(
        self,
        *,
        action: str,
        bucket_id: str,
        bucket_type: str,
        content: str,
        metadata: dict[str, object] | None,
    ) -> int:
        event = MemoryEvent.new(
            actor=ActorKind.SYSTEM,
            actor_name="legacy-runtime",
            memory_type=_memory_type(bucket_type),
            content=content,
            visibility=Visibility.PRIVATE,
            source_chain=("legacy_bucket_manager", str(action)),
            metadata={
                "legacy_action": str(action),
                "legacy_bucket_id": str(bucket_id),
                "legacy_bucket_type": str(bucket_type),
                "legacy_metadata": _json_safe(metadata or {}),
            },
        )
        return self.fabric.append_event(event)

    def purge_bucket_events(self, bucket_id: str) -> int:
        """Remove v3 fabric copies for a forgotten or purged legacy bucket."""
        return self.fabric.purge_legacy_bucket(str(bucket_id))

    def record_tool_event(self, tool_name: str, payload: dict[str, object] | None = None) -> int:
        name = str(tool_name)
        legacy_payload = _json_safe(payload or {})
        command_plan = self.command_bridge.plan_from_envelope(
            envelope := ExecutionEnvelope(
                    module=f"tools.{name}",
                    operation=name,
                    payload={k: v for k, v in legacy_payload.items() if k != "command_plan"},
                    actor_name="legacy-tool",
                    source="tools.record_v3_tool_event",
                    permissions=("mcp:call",),
                )
        )
        projection_metadata = self._projection_metadata(command_plan, legacy_payload)
        policy_metadata = self._policy_metadata(envelope, command_plan)
        event_sourced_metadata = self._event_sourced_metadata(
            envelope.module,
            envelope.operation,
            command_plan,
            legacy_payload,
        )
        retrieval_metadata = self._retrieval_metadata(name, legacy_payload)
        outcome_metadata = {"ok": True, "result_type": "tool_event"}
        command_boundary_metadata = self._command_boundary_metadata(
            envelope,
            command_plan,
            policy_metadata,
            outcome_metadata,
            event_type="LegacyToolRecorded",
        )
        decision_metadata = self._decision_metadata(
            envelope,
            command_plan,
            policy_metadata,
            projection_metadata,
            outcome_metadata,
        )
        event = MemoryEvent.new(
            actor=ActorKind.SYSTEM,
            actor_name="legacy-runtime",
            memory_type=MemoryType.TRACE,
            content=f"legacy tool invocation: {name}",
            visibility=Visibility.INTERNAL,
            source_chain=("legacy_tool", name),
            metadata={
                "legacy_tool_name": name,
                "legacy_payload": legacy_payload,
                "command_plan": command_plan.to_dict(),
                **event_sourced_metadata,
                **retrieval_metadata,
                **policy_metadata,
                **projection_metadata,
                **command_boundary_metadata,
                **decision_metadata,
            },
        )
        return self.fabric.append_event(event)

    def record_execution_event(self, envelope: ExecutionEnvelope, outcome: ExecutionOutcome) -> int:
        command_plan = self.command_bridge.plan_from_envelope(envelope)
        policy_metadata = self._policy_metadata(envelope, command_plan)
        projection_metadata = self._projection_metadata(
            command_plan,
            {
                "module": envelope.module,
                "operation": envelope.operation,
                "payload": envelope.sanitized_payload(),
                "ok": outcome.ok,
                "result_type": outcome.result_type,
                "error_type": outcome.error_type,
            },
        )
        event_sourced_metadata = self._event_sourced_metadata(
            envelope.module,
            envelope.operation,
            command_plan,
            {
                "module": envelope.module,
                "operation": envelope.operation,
                "payload": envelope.sanitized_payload(),
                "ok": outcome.ok,
                "result_type": outcome.result_type,
                "error_type": outcome.error_type,
            },
        )
        retrieval_metadata = self._retrieval_metadata(envelope.operation, envelope.sanitized_payload())
        outcome_metadata = {
            "ok": outcome.ok,
            "phase_history": list(outcome.phase_history),
            "result_type": outcome.result_type,
            "error_type": outcome.error_type,
            "error_message": outcome.error_message[:240],
        }
        command_boundary_metadata = self._command_boundary_metadata(
            envelope,
            command_plan,
            policy_metadata,
            outcome_metadata,
            event_type="LegacyExecutionRecorded",
        )
        decision_metadata = self._decision_metadata(
            envelope,
            command_plan,
            policy_metadata,
            projection_metadata,
            outcome_metadata,
        )
        event = MemoryEvent.new(
            actor=ActorKind.SYSTEM,
            actor_name="legacy-runtime",
            memory_type=MemoryType.TRACE,
            content=f"legacy operation: {envelope.module}.{envelope.operation} ok={outcome.ok}",
            visibility=Visibility.INTERNAL,
            source_chain=("legacy_execution", envelope.module, envelope.operation),
            metadata={
                "module": envelope.module,
                "operation": envelope.operation,
                "capability": envelope.capability,
                "actor_name": envelope.actor_name,
                "source": envelope.source,
                "ok": outcome.ok,
                "phase_history": list(outcome.phase_history),
                "result_type": outcome.result_type,
                "error_type": outcome.error_type,
                "error_message": outcome.error_message[:240],
                "payload": envelope.sanitized_payload(),
                "writes_memory": envelope.writes_memory,
                "protected_paths": list(envelope.protected_paths),
                "feature_flags": list(envelope.feature_flags),
                "command_plan": command_plan.to_dict(),
                **event_sourced_metadata,
                **retrieval_metadata,
                **policy_metadata,
                **projection_metadata,
                **command_boundary_metadata,
                **decision_metadata,
            },
        )
        return self.fabric.append_event(event)

    def plan_legacy_command(self, envelope: ExecutionEnvelope):
        return self.command_bridge.plan_from_envelope(envelope)

    def run_operation(self, envelope: ExecutionEnvelope, handler):
        return self.execution_pipeline.run(envelope, handler)

    async def run_async_operation(self, envelope: ExecutionEnvelope, handler):
        return await self.execution_pipeline.run_async(envelope, handler)

    def evaluate_update_manifest(self, manifest, content_by_path):
        return evaluate_update_manifest(manifest, content_by_path)

    def classify_static_surface(self, path: str):
        return self.static_surface_policy.classify(path)

    def debug_decisions(self, *, limit: int = 20, module: str = "", operation: str = "") -> dict[str, object]:
        return DecisionDebugService(self.fabric).list_records(limit=limit, module=module, operation=operation)

    def debug_decision(self, identifier: str) -> dict[str, object]:
        return DecisionDebugService(self.fabric).get_record(identifier)

    def replay_decision(self, identifier: str) -> dict[str, object]:
        return DecisionDebugService(self.fabric).replay(identifier)

    def debug_decision_health(self) -> dict[str, object]:
        return DecisionDebugService(self.fabric).health()

    def debug_command_boundary_health(self, *, limit: int = 50) -> dict[str, object]:
        return build_runtime_command_boundary_health(self.fabric.replay_events(), limit=limit)

    def compile_surface_context(
        self,
        decisions,
        memories,
        *,
        max_items: int = 8,
        excerpt_chars: int = 280,
    ) -> dict[str, object]:
        bundle = SurfaceContextCompiler(max_items=max_items, excerpt_chars=excerpt_chars).compile(decisions, memories)
        bundle_data = bundle.to_dict()
        invariant_report = FormalInvariantChecker.default().evaluate_context_items(
            [item.to_dict() for item in bundle.items]
        ).to_dict()
        return {
            "ok": bool(invariant_report.get("ok")),
            "compiler_version": bundle_data.get("compiler_version", ""),
            "item_count": bundle_data.get("item_count", 0),
            "truncated": bundle_data.get("truncated", False),
            "bundle": bundle_data,
            "formal_invariants": invariant_report,
        }

    def neural_route(
        self,
        tool: str,
        *,
        actor_name: str = "legacy-runtime",
        source: str = "mcp",
        permissions: tuple[str, ...] = (),
    ):
        return self.neural_tool_router.route(
            tool,
            scope=ToolScope(actor_name=actor_name, source=source, permissions=permissions),
        )

    def route_neural_tool(
        self,
        tool: str,
        *,
        actor_name: str = "legacy-runtime",
        source: str = "mcp",
        permissions: tuple[str, ...] = (),
    ) -> dict[str, object]:
        return self.neural_route(
            tool,
            actor_name=actor_name,
            source=source,
            permissions=permissions,
        ).to_dict()

    def tool_output_receipt(
        self,
        tool: str,
        *,
        summary: str = "",
        status: ToolOutputStatus | str = ToolOutputStatus.OK,
        actor_name: str = "legacy-runtime",
        source: str = "mcp",
        permissions: tuple[str, ...] = (),
        warnings: tuple[str, ...] = (),
    ):
        return self.tool_output_contract.from_route(
            self.neural_route(
                tool,
                actor_name=actor_name,
                source=source,
                permissions=permissions,
            ),
            status=status,
            summary=summary,
            warnings=warnings,
        )

    def evaluate_tool_output(
        self,
        tool: str,
        *,
        summary: str = "",
        status: ToolOutputStatus | str = ToolOutputStatus.OK,
        actor_name: str = "legacy-runtime",
        source: str = "mcp",
        permissions: tuple[str, ...] = (),
        warnings: tuple[str, ...] = (),
    ) -> dict[str, object]:
        receipt = self.tool_output_receipt(
            tool,
            summary=summary,
            status=status,
            actor_name=actor_name,
            source=source,
            permissions=permissions,
            warnings=warnings,
        )
        report = self.tool_output_contract.evaluate_receipt(receipt)
        return {
            "ok": report.ok,
            "receipt": receipt.to_dict(),
            "report": report.to_dict(),
        }

    def score_retrieval_bucket(
        self,
        bucket,
        features=None,
        *,
        gates=None,
        mode: str = "search",
        source: str = "",
    ) -> dict[str, object]:
        return self.retrieval_scorer.score_bucket(
            bucket,
            features,
            gates=gates,
            mode=mode,
            source=source,
        ).to_dict()

    def rank_retrieval_candidates(
        self,
        candidates,
        *,
        mode: str = "search",
        limit: int | None = None,
    ) -> list[dict[str, object]]:
        return [
            score.to_dict()
            for score in self.retrieval_scorer.rank(
                candidates,
                mode=mode,
                limit=limit,
            )
        ]

    def _projection_metadata(self, command_plan, legacy_metadata: dict[str, object]) -> dict[str, object]:
        try:
            return self.projection_audit_runtime.audit(command_plan, legacy_metadata)
        except Exception as exc:  # pragma: no cover - defensive side channel
            return {
                "projection_error": {
                    "error_type": type(exc).__name__,
                    "error_message": str(exc)[:240],
                }
            }

    def _policy_metadata(self, envelope: ExecutionEnvelope, command_plan) -> dict[str, object]:
        try:
            return {"policy_verdict": self.policy_engine.evaluate(envelope, command_plan)}
        except Exception as exc:  # pragma: no cover - defensive side channel
            return {
                "policy_error": {
                    "error_type": type(exc).__name__,
                    "error_message": str(exc)[:240],
                }
            }

    def _event_sourced_metadata(
        self,
        module: str,
        operation: str,
        command_plan,
        legacy_metadata: dict[str, object],
    ) -> dict[str, object]:
        try:
            envelope = self.event_sourced_kernel.prepare(
                module=module,
                operation=operation,
                command_plan=command_plan,
                legacy_metadata=legacy_metadata,
            )
            return {"event_sourced_kernel": envelope.summary()}
        except Exception as exc:  # pragma: no cover - defensive side channel
            return {
                "event_sourced_error": {
                    "error_type": type(exc).__name__,
                    "error_message": str(exc)[:240],
                }
            }

    def _retrieval_metadata(self, operation: str, payload: dict[str, object]) -> dict[str, object]:
        if str(operation) not in {"breath", "search"}:
            return {}
        try:
            plan = self.query_planner.plan(payload, operation=str(operation))
            return {
                "retrieval_plan": plan.to_dict(),
                "retrieval_trace": self.retrieval_engine.trace(plan),
            }
        except Exception as exc:  # pragma: no cover - defensive side channel
            return {
                "retrieval_error": {
                    "error_type": type(exc).__name__,
                    "error_message": str(exc)[:240],
                }
            }

    def _decision_metadata(
        self,
        envelope: ExecutionEnvelope,
        command_plan,
        policy_metadata: dict[str, object],
        projection_metadata: dict[str, object],
        outcome: dict[str, object],
    ) -> dict[str, object]:
        try:
            record = self.decision_ledger.record(
                module=envelope.module,
                operation=envelope.operation,
                command_plan=command_plan.to_dict(),
                policy_metadata=policy_metadata,
                projection_metadata=projection_metadata,
                outcome=outcome,
            )
            return {"decision_record": record.to_dict()}
        except Exception as exc:  # pragma: no cover - defensive side channel
            return {
                "decision_error": {
                    "error_type": type(exc).__name__,
                    "error_message": str(exc)[:240],
                }
            }

    def _command_boundary_metadata(
        self,
        envelope: ExecutionEnvelope,
        command_plan,
        policy_metadata: dict[str, object],
        outcome: dict[str, object],
        *,
        event_type: str,
    ) -> dict[str, object]:
        try:
            policy_allowed = _effective_policy_allowed(policy_metadata)
            outcome_ok = bool(outcome.get("ok", True))
            writes_memory = bool(command_plan.writes_memory)
            ledger_appended = writes_memory and policy_allowed and outcome_ok
            stages = _boundary_stages(writes_memory=writes_memory, ledger_appended=ledger_appended)
            events = _boundary_events(
                command_plan,
                envelope,
                event_type=event_type,
                include_event=ledger_appended,
            )
            receipt = CommandBoundaryReceipt(
                command_id=command_plan.command_id,
                command_kind=command_plan.command_kind.value,
                stages=stages,
                events=events,
                ledger_appended=ledger_appended,
                policy_preflight_allowed=policy_allowed,
                event_validation_allowed=True,
                metadata={
                    "module": envelope.module,
                    "operation": envelope.operation,
                    "source": envelope.source,
                    "outcome_ok": outcome_ok,
                    "writes_memory": writes_memory,
                    "runtime_event_type": event_type,
                },
            )
            report = AdvancedCommandBoundaryContract.default().evaluate_receipt(receipt)
            return {"command_boundary": {"receipt": receipt.to_dict(), "report": report.to_dict()}}
        except Exception as exc:  # pragma: no cover - defensive side channel
            return {
                "command_boundary_error": {
                    "error_type": type(exc).__name__,
                    "error_message": str(exc)[:240],
                }
            }


def _memory_type(value: object) -> MemoryType:
    try:
        return MemoryType(str(value).lower())
    except ValueError:
        return MemoryType.DYNAMIC


def _json_safe(value: object) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False, default=str))


def _effective_policy_allowed(policy_metadata: dict[str, object]) -> bool:
    verdict = policy_metadata.get("policy_verdict")
    if isinstance(verdict, dict):
        if "effective_allowed" in verdict:
            return bool(verdict["effective_allowed"])
        if "allowed" in verdict:
            return bool(verdict["allowed"])
    return "policy_error" not in policy_metadata


def _boundary_stages(*, writes_memory: bool, ledger_appended: bool) -> tuple[BoundaryStage, ...]:
    if writes_memory and ledger_appended:
        return (
            BoundaryStage.COMMAND,
            BoundaryStage.POLICY_PREFLIGHT,
            BoundaryStage.EVENT_DERIVATION,
            BoundaryStage.EVENT_POLICY_VALIDATION,
            BoundaryStage.LEDGER_APPEND,
            BoundaryStage.RECEIPT,
        )
    return (
        BoundaryStage.COMMAND,
        BoundaryStage.POLICY_PREFLIGHT,
        BoundaryStage.RECEIPT,
    )


def _boundary_events(
    command_plan,
    envelope: ExecutionEnvelope,
    *,
    event_type: str,
    include_event: bool,
) -> tuple[dict[str, object], ...]:
    if not include_event:
        return ()
    return (
        {
            "event_type": event_type,
            "command_id": command_plan.command_id,
            "module": envelope.module,
            "operation": envelope.operation,
        },
    )


def _policy_enforcement_mode(config: dict[str, Any]) -> object:
    policy_config = config.get("policy")
    if isinstance(policy_config, dict):
        nested_mode = policy_config.get("enforcement_mode")
        if nested_mode:
            return nested_mode
    return config.get("policy_enforcement_mode", "audit")
