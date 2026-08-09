from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import json
from typing import Any, Mapping


class ArtifactLanguage(Enum):
    PYTHON = "python"
    RUST = "rust"
    OTHER = "other"


class ArtifactRole(Enum):
    ADAPTER = "adapter"
    KERNEL = "kernel"
    PROJECTION = "projection"
    DASHBOARD_ACTION = "dashboard_action"
    ASYNC_TASK = "async_task"
    POLICY_RULE = "policy_rule"
    MIGRATION = "migration"
    PLUGIN = "plugin"
    OTHER = "other"


@dataclass(frozen=True)
class CodeArtifactSpec:
    path: str
    language: ArtifactLanguage | str
    role: ArtifactRole | str
    type_checked: bool = True
    uses_explicit_commands: bool = True
    directly_mutates_canonical_memory: bool = False
    appends_ledger_events: bool = True
    exposes_hard_delete_api: bool = False
    validates_policy: bool = True
    denial_reasons_explicit: bool = True
    async_idempotent: bool = True
    reports_projection_lag: bool = True
    capability_scoped: bool = True
    change_kind: str = ""
    adr_path: str = ""
    tests: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", str(self.path))
        object.__setattr__(self, "language", _coerce_language(self.language))
        object.__setattr__(self, "role", _coerce_role(self.role))
        object.__setattr__(self, "type_checked", bool(self.type_checked))
        object.__setattr__(self, "uses_explicit_commands", bool(self.uses_explicit_commands))
        object.__setattr__(self, "directly_mutates_canonical_memory", bool(self.directly_mutates_canonical_memory))
        object.__setattr__(self, "appends_ledger_events", bool(self.appends_ledger_events))
        object.__setattr__(self, "exposes_hard_delete_api", bool(self.exposes_hard_delete_api))
        object.__setattr__(self, "validates_policy", bool(self.validates_policy))
        object.__setattr__(self, "denial_reasons_explicit", bool(self.denial_reasons_explicit))
        object.__setattr__(self, "async_idempotent", bool(self.async_idempotent))
        object.__setattr__(self, "reports_projection_lag", bool(self.reports_projection_lag))
        object.__setattr__(self, "capability_scoped", bool(self.capability_scoped))
        object.__setattr__(self, "change_kind", str(self.change_kind))
        object.__setattr__(self, "adr_path", str(self.adr_path))
        object.__setattr__(self, "tests", tuple(_normalize_test_name(test) for test in self.tests))
        object.__setattr__(self, "metadata", _json_safe_dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "language": self.language.value,
            "role": self.role.value,
            "type_checked": self.type_checked,
            "uses_explicit_commands": self.uses_explicit_commands,
            "directly_mutates_canonical_memory": self.directly_mutates_canonical_memory,
            "appends_ledger_events": self.appends_ledger_events,
            "exposes_hard_delete_api": self.exposes_hard_delete_api,
            "validates_policy": self.validates_policy,
            "denial_reasons_explicit": self.denial_reasons_explicit,
            "async_idempotent": self.async_idempotent,
            "reports_projection_lag": self.reports_projection_lag,
            "capability_scoped": self.capability_scoped,
            "change_kind": self.change_kind,
            "adr_path": self.adr_path,
            "tests": list(self.tests),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class CodeStandardIssue:
    code: str
    message: str
    path: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", str(self.code))
        object.__setattr__(self, "message", str(self.message))
        object.__setattr__(self, "path", str(self.path))
        object.__setattr__(self, "metadata", _json_safe_dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "path": self.path,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class CodeStandardReport:
    artifacts: tuple[str, ...]
    issues: tuple[CodeStandardIssue, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifacts", tuple(str(path) for path in self.artifacts))
        object.__setattr__(self, "issues", tuple(self.issues))

    @property
    def ok(self) -> bool:
        return not self.issues

    @property
    def artifact_count(self) -> int:
        return len(self.artifacts)

    @property
    def issue_count(self) -> int:
        return len(self.issues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "artifact_count": self.artifact_count,
            "issue_count": self.issue_count,
            "artifacts": list(self.artifacts),
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class HighestDifficultyCodeStandards:
    adr_required_change_kinds: frozenset[str]

    @classmethod
    def default(cls) -> "HighestDifficultyCodeStandards":
        return cls(
            adr_required_change_kinds=frozenset(
                {
                    "new_memory_kind",
                    "deletion_behavior_change",
                    "archive_behavior_change",
                    "total_recall_like_feature",
                    "plugin_capability_expansion",
                    "affective_scoring_change",
                    "dream_behavior_change",
                }
            )
        )

    def evaluate_artifact(self, spec: CodeArtifactSpec | Mapping[str, Any]) -> CodeStandardReport:
        artifact = _coerce_spec(spec)
        issues = list(self._evaluate_spec(artifact))
        return CodeStandardReport(artifacts=(artifact.path,), issues=tuple(issues))

    def evaluate_manifest(self, specs: list[CodeArtifactSpec] | tuple[CodeArtifactSpec, ...]) -> CodeStandardReport:
        artifacts: list[str] = []
        issues: list[CodeStandardIssue] = []
        for raw_spec in specs:
            spec = _coerce_spec(raw_spec)
            artifacts.append(spec.path)
            issues.extend(self._evaluate_spec(spec))
        return CodeStandardReport(artifacts=tuple(artifacts), issues=tuple(issues))

    def _evaluate_spec(self, spec: CodeArtifactSpec) -> tuple[CodeStandardIssue, ...]:
        issues: list[CodeStandardIssue] = []
        if spec.language == ArtifactLanguage.PYTHON:
            issues.extend(self._python_issues(spec))
        if spec.language == ArtifactLanguage.RUST or spec.role == ArtifactRole.KERNEL:
            issues.extend(self._kernel_issues(spec))
        issues.extend(self._role_issues(spec))
        issues.extend(self._adr_issues(spec))
        if spec.exposes_hard_delete_api:
            issues.append(
                _issue(
                    "normal_hard_delete_api_exposed",
                    "normal code paths must not expose hard-delete APIs",
                    spec,
                )
            )
        return tuple(issues)

    def _python_issues(self, spec: CodeArtifactSpec) -> tuple[CodeStandardIssue, ...]:
        issues: list[CodeStandardIssue] = []
        if not spec.type_checked:
            issues.append(_issue("python_boundary_not_typed", "Python boundary code must be typed", spec))
        if spec.directly_mutates_canonical_memory:
            issues.append(
                _issue(
                    "python_direct_canonical_mutation",
                    "Python adapters must not directly mutate canonical memory",
                    spec,
                )
            )
        if not spec.uses_explicit_commands:
            issues.append(
                _issue(
                    "python_missing_explicit_command_boundary",
                    "Python adapters must cross memory mutation boundaries through explicit commands",
                    spec,
                )
            )
        return tuple(issues)

    def _kernel_issues(self, spec: CodeArtifactSpec) -> tuple[CodeStandardIssue, ...]:
        issues: list[CodeStandardIssue] = []
        if spec.directly_mutates_canonical_memory:
            issues.append(
                _issue(
                    "rust_unchecked_canonical_mutation",
                    "kernel canonical trace state cannot be mutated without event validation",
                    spec,
                )
            )
        if not spec.appends_ledger_events:
            issues.append(
                _issue(
                    "rust_kernel_not_append_only",
                    "kernel mutation APIs must emit append-only ledger events",
                    spec,
                )
            )
        if not spec.validates_policy:
            issues.append(
                _issue(
                    "rust_kernel_bypasses_policy_vm",
                    "kernel command execution must pass through the Policy VM",
                    spec,
                )
            )
        if not spec.denial_reasons_explicit:
            issues.append(
                _issue(
                    "policy_denial_reasons_not_explicit",
                    "Policy VM denials must carry explicit reasons",
                    spec,
                )
            )
        return tuple(issues)

    def _role_issues(self, spec: CodeArtifactSpec) -> tuple[CodeStandardIssue, ...]:
        issues: list[CodeStandardIssue] = []
        if spec.role == ArtifactRole.ASYNC_TASK and not spec.async_idempotent:
            issues.append(_issue("async_task_not_idempotent", "async tasks must be idempotent", spec))
        if spec.role == ArtifactRole.PROJECTION and not spec.reports_projection_lag:
            issues.append(_issue("projection_lag_not_reported", "projections may lag but must report lag", spec))
        if spec.role == ArtifactRole.DASHBOARD_ACTION and not spec.capability_scoped:
            issues.append(
                _issue(
                    "dashboard_action_not_capability_scoped",
                    "dashboard actions must be capability-scoped",
                    spec,
                )
            )
        return tuple(issues)

    def _adr_issues(self, spec: CodeArtifactSpec) -> tuple[CodeStandardIssue, ...]:
        if spec.change_kind not in self.adr_required_change_kinds:
            return ()
        issues: list[CodeStandardIssue] = []
        if not spec.adr_path:
            issues.append(
                _issue(
                    "adr_required_missing",
                    "philosophy-touching changes must include an ADR",
                    spec,
                    change_kind=spec.change_kind,
                )
            )
            return tuple(issues)
        tests = set(spec.tests)
        if "property" not in tests:
            issues.append(
                _issue(
                    "adr_change_missing_property_tests",
                    "ADR-backed philosophy changes must include property test evidence",
                    spec,
                    change_kind=spec.change_kind,
                    adr_path=spec.adr_path,
                )
            )
        if spec.role == ArtifactRole.POLICY_RULE and "mutation" not in tests:
            issues.append(
                _issue(
                    "adr_change_missing_mutation_tests",
                    "policy ADR changes should include mutation-test evidence",
                    spec,
                    change_kind=spec.change_kind,
                    adr_path=spec.adr_path,
                )
            )
        return tuple(issues)


def _coerce_language(value: ArtifactLanguage | str) -> ArtifactLanguage:
    if isinstance(value, ArtifactLanguage):
        return value
    raw = str(value)
    try:
        return ArtifactLanguage(raw)
    except ValueError:
        return ArtifactLanguage.OTHER


def _coerce_role(value: ArtifactRole | str) -> ArtifactRole:
    if isinstance(value, ArtifactRole):
        return value
    raw = str(value)
    try:
        return ArtifactRole(raw)
    except ValueError:
        return ArtifactRole.OTHER


def _coerce_spec(spec: CodeArtifactSpec | Mapping[str, Any]) -> CodeArtifactSpec:
    if isinstance(spec, CodeArtifactSpec):
        return spec
    return CodeArtifactSpec(**dict(spec))


def _issue(code: str, message: str, spec: CodeArtifactSpec, **metadata: Any) -> CodeStandardIssue:
    return CodeStandardIssue(code=code, message=message, path=spec.path, metadata=metadata)


def _normalize_test_name(value: str) -> str:
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def _json_safe_dict(value: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(dict(value), ensure_ascii=False, allow_nan=False, default=str))
