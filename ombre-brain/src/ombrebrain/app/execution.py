from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum
import json
import logging
from typing import Any, TypeVar

from ombrebrain.kernel.errors import PolicyViolation

logger = logging.getLogger("ombrebrain.app.execution")

T = TypeVar("T")


class ExecutionPhase(Enum):
    RECEIVED = "received"
    VALIDATING = "validating"
    AUTHORIZING = "authorizing"
    EXECUTING = "executing"
    APPLYING = "applying"
    RECORDING = "recording"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class ExecutionEnvelope:
    module: str
    operation: str
    payload: Mapping[str, Any] | None = None
    actor_name: str = "legacy-runtime"
    source: str = "legacy"
    permissions: tuple[str, ...] = field(default_factory=tuple)
    required_permissions: tuple[str, ...] = field(default_factory=tuple)
    capability: str = ""
    writes_memory: bool = False
    protected_paths: tuple[str, ...] = field(default_factory=tuple)
    feature_flags: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "module", str(self.module).strip())
        object.__setattr__(self, "operation", str(self.operation).strip())
        object.__setattr__(self, "payload", dict(self.payload or {}))
        object.__setattr__(self, "actor_name", str(self.actor_name or "legacy-runtime"))
        object.__setattr__(self, "source", str(self.source or "legacy"))
        object.__setattr__(self, "permissions", tuple(str(item) for item in self.permissions))
        object.__setattr__(self, "required_permissions", tuple(str(item) for item in self.required_permissions))
        object.__setattr__(self, "capability", str(self.capability or ""))
        object.__setattr__(self, "protected_paths", tuple(str(item) for item in self.protected_paths))
        object.__setattr__(self, "feature_flags", tuple(str(item) for item in self.feature_flags))

    def sanitized_payload(self) -> dict[str, Any]:
        return _sanitize_payload(dict(self.payload or {}))


@dataclass(frozen=True)
class ExecutionOutcome:
    ok: bool
    phase_history: tuple[str, ...]
    result_type: str = ""
    error_type: str = ""
    error_message: str = ""


class LegacyExecutionPipeline:
    """Best-effort execution envelope for legacy modules.

    The pipeline intentionally returns handler results unchanged and re-raises
    handler exceptions unchanged. The v2.4.0 side channel records behavior; it does
    not become a new source of visible legacy behavior.
    """

    def __init__(self, runtime: object | None = None):
        self.runtime = runtime

    def run(self, envelope: ExecutionEnvelope, handler: Callable[[], T]) -> T:
        history = self._preflight(envelope)
        self._authorize_policy(envelope, history)
        try:
            history.append(ExecutionPhase.EXECUTING.value)
            result = handler()
        except Exception as exc:
            history.append(ExecutionPhase.FAILED.value)
            self._record(
                envelope,
                ExecutionOutcome(
                    ok=False,
                    phase_history=tuple(history),
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                ),
            )
            raise

        history.extend((ExecutionPhase.RECORDING.value, ExecutionPhase.COMPLETED.value))
        self._record(
            envelope,
            ExecutionOutcome(
                ok=True,
                phase_history=tuple(history),
                result_type=type(result).__name__,
            ),
        )
        return result

    async def run_async(
        self,
        envelope: ExecutionEnvelope,
        handler: Callable[[], Awaitable[T]],
    ) -> T:
        history = self._preflight(envelope)
        self._authorize_policy(envelope, history)
        try:
            history.append(ExecutionPhase.EXECUTING.value)
            result = await handler()
        except Exception as exc:
            history.append(ExecutionPhase.FAILED.value)
            self._record(
                envelope,
                ExecutionOutcome(
                    ok=False,
                    phase_history=tuple(history),
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                ),
            )
            raise

        history.extend((ExecutionPhase.RECORDING.value, ExecutionPhase.COMPLETED.value))
        self._record(
            envelope,
            ExecutionOutcome(
                ok=True,
                phase_history=tuple(history),
                result_type=type(result).__name__,
            ),
        )
        return result

    def _preflight(self, envelope: ExecutionEnvelope) -> list[str]:
        history = [ExecutionPhase.RECEIVED.value, ExecutionPhase.VALIDATING.value]
        if not envelope.module:
            raise ValueError("execution envelope module is required")
        if not envelope.operation:
            raise ValueError("execution envelope operation is required")
        _json_safe(envelope.sanitized_payload())
        history.append(ExecutionPhase.AUTHORIZING.value)
        missing = set(envelope.required_permissions) - set(envelope.permissions)
        if missing:
            raise PermissionError(f"missing permissions: {sorted(missing)}")
        return history

    def _authorize_policy(self, envelope: ExecutionEnvelope, history: list[str]) -> None:
        verdict = self._policy_verdict(envelope)
        if not verdict or bool(verdict.get("effective_allowed", True)):
            return

        message = _policy_violation_message(envelope, verdict)
        history.append(ExecutionPhase.FAILED.value)
        self._record(
            envelope,
            ExecutionOutcome(
                ok=False,
                phase_history=tuple(history),
                error_type=PolicyViolation.__name__,
                error_message=message,
            ),
        )
        raise PolicyViolation(message)

    def _policy_verdict(self, envelope: ExecutionEnvelope) -> dict[str, Any] | None:
        planner = getattr(self.runtime, "plan_legacy_command", None)
        policy_engine = getattr(self.runtime, "policy_engine", None)
        evaluator = getattr(policy_engine, "evaluate", None)
        if not callable(planner) or not callable(evaluator):
            return None
        try:
            verdict = evaluator(envelope, planner(envelope))
        except Exception as exc:  # pragma: no cover - defensive side channel
            logger.warning("v2.4.0 policy evaluation failed for %s.%s: %s", envelope.module, envelope.operation, exc)
            return None
        if isinstance(verdict, Mapping):
            return dict(verdict)
        return None

    def _record(self, envelope: ExecutionEnvelope, outcome: ExecutionOutcome) -> None:
        recorder = getattr(self.runtime, "record_execution_event", None)
        if not callable(recorder):
            return
        try:
            recorder(envelope, outcome)
        except Exception as exc:  # pragma: no cover - defensive side channel
            logger.warning("v2.4.0 execution event record failed for %s.%s: %s", envelope.module, envelope.operation, exc)


_SENSITIVE_PARTS = (
    "token",
    "secret",
    "password",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "session",
    "oauth",
)


def _sanitize_payload(value: Any) -> Any:
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key_str = str(key)
            if _is_sensitive_key(key_str):
                sanitized[key_str] = "[REDACTED]"
            else:
                sanitized[key_str] = _sanitize_payload(item)
        return sanitized
    if isinstance(value, (list, tuple)):
        return [_sanitize_payload(item) for item in value]
    return _json_safe(value)


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in _SENSITIVE_PARTS)


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False, default=str))


def _policy_violation_message(envelope: ExecutionEnvelope, verdict: Mapping[str, Any]) -> str:
    missing = ", ".join(str(item) for item in verdict.get("missing_permissions", ()))
    protected = ", ".join(str(item) for item in verdict.get("protected_surfaces", ()))
    details: list[str] = []
    if missing:
        details.append(f"missing permissions: {missing}")
    if protected:
        details.append(f"protected surfaces: {protected}")
    suffix = f" ({'; '.join(details)})" if details else ""
    return f"policy denied {envelope.module}.{envelope.operation}{suffix}"
