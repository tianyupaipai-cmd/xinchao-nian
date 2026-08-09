from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any

from ombrebrain.decision.debug import DecisionDebugService
from ombrebrain.fabric.storage.engine import MemoryFabric


@dataclass(frozen=True)
class ResilienceFinding:
    code: str
    severity: str
    message: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", str(self.code))
        object.__setattr__(self, "severity", str(self.severity))
        object.__setattr__(self, "message", str(self.message))
        object.__setattr__(self, "metadata", _json_safe(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ResilienceReport:
    ok: bool
    event_count: int
    findings: tuple[ResilienceFinding, ...]
    checks: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "event_count": self.event_count,
            "finding_count": len(self.findings),
            "findings": [finding.to_dict() for finding in self.findings],
            "checks": dict(self.checks),
        }


@dataclass(frozen=True)
class V3ResilienceScanner:
    fabric: MemoryFabric

    def scan(self) -> ResilienceReport:
        findings: list[ResilienceFinding] = []
        checks: dict[str, Any] = {}
        events = []
        try:
            events = self.fabric.replay_events()
            checks["wal_replay"] = "ok"
        except Exception as exc:
            checks["wal_replay"] = "failed"
            findings.append(
                ResilienceFinding(
                    code="wal_replay_failed",
                    severity="error",
                    message="v2.4.0 WAL replay failed",
                    metadata={"error_type": type(exc).__name__, "error_message": str(exc)[:240]},
                )
            )
            return ResilienceReport(ok=False, event_count=0, findings=tuple(findings), checks=checks)

        findings.extend(self._decision_findings())
        findings.extend(self._metadata_shape_findings(events))
        checks["decision_debug"] = "ok" if not any(f.code == "decision_metadata_problem" for f in findings) else "problem"
        checks["metadata_shape"] = "ok" if not any(f.code == "metadata_shape_drift" for f in findings) else "problem"
        ok = not any(finding.severity == "error" for finding in findings)
        return ResilienceReport(ok=ok, event_count=len(events), findings=tuple(findings), checks=checks)

    def _decision_findings(self) -> tuple[ResilienceFinding, ...]:
        try:
            listing = DecisionDebugService(self.fabric).list_records(limit=20)
        except Exception as exc:  # pragma: no cover - defensive service boundary
            return (
                ResilienceFinding(
                    code="decision_debug_failed",
                    severity="error",
                    message="decision debug service failed",
                    metadata={"error_type": type(exc).__name__, "error_message": str(exc)[:240]},
                ),
            )
        findings = []
        for problem in listing.get("problems", []):
            findings.append(
                ResilienceFinding(
                    code="decision_metadata_problem",
                    severity="error",
                    message="decision metadata problem detected",
                    metadata=_as_dict(problem),
                )
            )
        return tuple(findings)

    def _metadata_shape_findings(self, events) -> tuple[ResilienceFinding, ...]:
        findings: list[ResilienceFinding] = []
        expected_objects = ("command_plan", "policy_verdict", "projection_journal", "consistency_report")
        for event in events:
            metadata = event.metadata
            if not any(key in metadata for key in expected_objects):
                continue
            for key in expected_objects:
                if key in metadata and not isinstance(metadata[key], dict):
                    findings.append(
                        ResilienceFinding(
                            code="metadata_shape_drift",
                            severity="error",
                            message="v2.4.0 trace metadata field has unexpected shape",
                            metadata={"event_id": event.id, "field": key, "observed_type": type(metadata[key]).__name__},
                        )
                    )
        return tuple(findings)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {"value": value}


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False, default=str))
