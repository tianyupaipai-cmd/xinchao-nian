from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping


@dataclass(frozen=True)
class VNextCoverageItem:
    phase_key: str
    title: str
    status: str = "implemented"
    plan_path: str = ""
    test_files: tuple[str, ...] = ()
    preflight_checks: tuple[str, ...] = ()
    notes: str = ""

    def to_dict(self, available_checks: set[str]) -> dict[str, Any]:
        covered_checks = tuple(check for check in self.preflight_checks if check in available_checks)
        return {
            "phase_key": self.phase_key,
            "title": self.title,
            "status": self.status,
            "plan_path": self.plan_path,
            "test_files": list(self.test_files),
            "preflight_checks": list(self.preflight_checks),
            "preflight_covered": bool(covered_checks),
            "available_preflight_checks": list(covered_checks),
            "notes": self.notes,
        }


@dataclass(frozen=True)
class VNextCoverageMatrix:
    items: tuple[VNextCoverageItem, ...]
    schema: str = "vnext-coverage.v1"

    @classmethod
    def default(cls) -> "VNextCoverageMatrix":
        return cls(_DEFAULT_ITEMS)

    def evaluate(self, checks: Mapping[str, object]) -> dict[str, Any]:
        available_checks = {str(name) for name in checks}
        available_checks.add("vnext_coverage")
        item_data = [item.to_dict(available_checks) for item in self.items]
        implemented = [item for item in item_data if item["status"] in {"implemented", "shadow", "contract"}]
        preflight_covered = [item for item in item_data if item["preflight_covered"]]
        preflight_gaps = [item for item in item_data if item["status"] in {"implemented", "shadow", "contract"} and not item["preflight_covered"]]
        test_covered = [item for item in item_data if item["test_files"]]
        return _json_safe(
            {
                "ok": True,
                "status": "ok",
                "schema": self.schema,
                "phase_count": len(item_data),
                "implemented_count": len(implemented),
                "test_covered_count": len(test_covered),
                "preflight_covered_count": len(preflight_covered),
                "preflight_gap_count": len(preflight_gaps),
                "local_completion_percent": _percent(len(implemented), len(item_data)),
                "preflight_coverage_percent": _percent(len(preflight_covered), len(item_data)),
                "preflight_gaps": preflight_gaps,
                "next_preflight_targets": preflight_gaps[:5],
                "items": item_data,
            }
        )


def _item(
    phase_key: str,
    title: str,
    plan_slug: str,
    *,
    tests: tuple[str, ...],
    checks: tuple[str, ...] = (),
    notes: str = "",
) -> VNextCoverageItem:
    return VNextCoverageItem(
        phase_key=phase_key,
        title=title,
        plan_path=f"docs/superpowers/plans/{plan_slug}",
        test_files=tests,
        preflight_checks=checks,
        notes=notes,
    )


_DEFAULT_ITEMS: tuple[VNextCoverageItem, ...] = (
    _item(
        "phase_1",
        "Ledger mirror",
        "2026-07-02-ledger-mirror-phase1.md",
        tests=("tests/test_ledger_mirror_phase1.py",),
        checks=("ledger_mirror",),
        notes="Preflight samples the append-only JSONL mirror shape; live BucketManager wiring remains covered by tests.",
    ),
    _item(
        "phase_2a",
        "Rebuildable in-memory projection",
        "2026-07-02-rebuildable-projection-phase2.md",
        tests=("tests/test_projection_mirror_phase2.py",),
        checks=("trace_catalog_projection",),
    ),
    _item(
        "phase_2b",
        "SQLite/FTS shadow projection",
        "2026-07-03-sqlite-projection-phase2b.md",
        tests=("tests/test_sqlite_projection_phase2b.py",),
        checks=("sqlite_projection",),
    ),
    _item(
        "phase_2c",
        "Vector projection manifest",
        "2026-07-03-vector-projection-phase2c.md",
        tests=("tests/test_vector_projection_phase2c.py",),
        checks=("vector_projection",),
    ),
    _item(
        "phase_3a",
        "Surface policy VM",
        "2026-07-02-surface-policy-phase3.md",
        tests=("tests/test_surface_policy_phase3.py",),
        checks=("retrieval_scoring", "surface_context"),
    ),
    _item(
        "phase_3b",
        "Dashboard search surface policy",
        "2026-07-03-search-surface-policy-phase3b.md",
        tests=("tests/test_surface_policy_phase3.py",),
        checks=("retrieval_scoring",),
    ),
    _item(
        "phase_3c",
        "Breath search surface policy",
        "2026-07-03-breath-search-surface-policy-phase3c.md",
        tests=("tests/test_surface_policy_phase3.py",),
        checks=("retrieval_scoring",),
    ),
    _item(
        "phase_4",
        "Tombstone-only erasure shadow",
        "2026-07-02-tombstone-erasure-phase4.md",
        tests=("tests/test_tombstone_erasure_phase4.py",),
        checks=("formal_invariants", "migration_preservation"),
    ),
    _item(
        "phase_5a",
        "Ledger replay validator",
        "2026-07-02-ledger-replay-phase5a.md",
        tests=("tests/test_ledger_replay_phase5a.py",),
        checks=("ledger_replay",),
    ),
    _item(
        "phase_5b",
        "Deterministic ledger property runner",
        "2026-07-02-ledger-property-phase5b.md",
        tests=("tests/test_ledger_property_phase5b.py",),
        checks=("ledger_property",),
    ),
    _item(
        "phase_6a",
        "Rust replay kernel scaffold",
        "2026-07-02-rust-kernel-phase6a.md",
        tests=("tests/test_rust_kernel_phase6a.py",),
        checks=("rust_kernel_scaffold",),
        notes="Scaffold only; Rust extraction remains non-blocking.",
    ),
    _item(
        "phase_7a",
        "Policy effective/audit verdicts",
        "2026-07-03-policy-enforcement-phase7a.md",
        tests=("tests/test_v3_policy_engine.py",),
        checks=("policy_verdicts",),
    ),
    _item(
        "phase_7b",
        "Executable policy enforcement boundary",
        "2026-07-03-policy-enforcement-phase7b.md",
        tests=("tests/test_v3_legacy_execution_pipeline.py",),
        checks=("runtime_command_boundary",),
    ),
    _item(
        "phase_7c",
        "Plugin capability enforcement",
        "2026-07-03-plugin-capability-enforcement-phase7c.md",
        tests=("tests/test_v3_plugin_runtime.py",),
        checks=("plugin_capability_enforcement",),
    ),
    _item(
        "phase_8a",
        "Formal invariants shadow checker",
        "2026-07-05-formal-invariants-phase8a.md",
        tests=("tests/test_formal_invariants_phase8a.py",),
        checks=("formal_invariants",),
    ),
    _item(
        "phase_8b",
        "Context serialization contract",
        "2026-07-05-context-serialization-phase8b.md",
        tests=("tests/test_context_serialization_phase8b.py",),
        checks=("context_serialization",),
    ),
    _item(
        "phase_8c",
        "Neural tool router shadow contract",
        "2026-07-05-neural-tool-router-phase8c.md",
        tests=("tests/test_neural_tool_router_phase8c.py",),
        checks=("tool_output_humility",),
    ),
    _item(
        "phase_8d",
        "Tool output humility contract",
        "2026-07-05-tool-output-contract-phase8d.md",
        tests=("tests/test_tool_output_contract_phase8d.py",),
        checks=("tool_output_humility",),
    ),
    _item(
        "phase_9",
        "Policy-gated retrieval scoring",
        "2026-07-05-retrieval-scoring-phase9.md",
        tests=("tests/test_retrieval_scoring_phase9.py",),
        checks=("retrieval_scoring",),
    ),
    _item(
        "phase_10",
        "Formal invariants coverage extension",
        "2026-07-05-formal-invariants-phase10.md",
        tests=("tests/test_formal_invariants_phase10.py",),
        checks=("formal_invariants",),
    ),
    _item(
        "phase_11",
        "Plugin agency boundary",
        "2026-07-05-plugin-agency-boundary-phase11.md",
        tests=("tests/test_plugin_agency_boundary_phase11.py",),
        checks=("red_lines",),
    ),
    _item(
        "phase_12",
        "Observability metric boundary",
        "2026-07-05-observability-boundary-phase12.md",
        tests=("tests/test_observability_boundary_phase12.py",),
        checks=("observability_boundary",),
    ),
    _item(
        "phase_13",
        "Crash recovery contract",
        "2026-07-05-crash-recovery-phase13.md",
        tests=("tests/test_crash_recovery_phase13.py",),
        checks=("crash_recovery",),
    ),
    _item(
        "phase_14",
        "Replication contract",
        "2026-07-05-replication-contract-phase14.md",
        tests=("tests/test_replication_contract_phase14.py",),
        checks=("replication_contract",),
    ),
    _item(
        "phase_15",
        "Migration preservation contract",
        "2026-07-05-migration-contract-phase15.md",
        tests=("tests/test_migration_contract_phase15.py",),
        checks=("migration_preservation",),
    ),
    _item(
        "phase_16",
        "Public MCP tool design contract",
        "2026-07-05-public-tool-design-phase16.md",
        tests=("tests/test_public_tool_design_phase16.py",),
        checks=("public_tools",),
    ),
    _item(
        "phase_17",
        "Highest difficulty code standards",
        "2026-07-05-code-standards-phase17.md",
        tests=("tests/test_code_standards_phase17.py",),
        checks=("code_standards",),
    ),
    _item(
        "phase_18",
        "Advanced command boundary contract",
        "2026-07-05-command-boundary-phase18.md",
        tests=("tests/test_command_boundary_phase18.py",),
        checks=("command_boundary", "runtime_command_boundary"),
    ),
    _item(
        "phase_19",
        "Surface context compiler",
        "2026-07-05-surface-context-compiler-phase19.md",
        tests=("tests/test_surface_context_compiler_phase19.py",),
        checks=("surface_context",),
    ),
    _item(
        "phase_20",
        "ADR requirements contract",
        "2026-07-05-adr-requirements-phase20.md",
        tests=("tests/test_adr_requirements_phase20.py",),
        checks=("adr_requirements",),
    ),
    _item(
        "phase_21",
        "Red lines contract",
        "2026-07-05-red-lines-phase21.md",
        tests=("tests/test_red_lines_phase21.py",),
        checks=("red_lines",),
    ),
    _item(
        "phase_22",
        "vNext preflight report",
        "2026-07-05-vnext-preflight-phase22.md",
        tests=("tests/test_vnext_preflight_report_phase22.py",),
        checks=("preflight_report_self",),
    ),
    _item(
        "phase_23",
        "vNext preflight CLI and diagnostics",
        "2026-07-05-vnext-preflight-cli-diagnostics-phase23.md",
        tests=("tests/test_v3_maintenance_report.py", "tests/test_system_diagnostics.py"),
        checks=("preflight_cli_diagnostics",),
    ),
    _item(
        "phase_24",
        "Runtime command boundary preflight",
        "2026-07-05-runtime-command-boundary-preflight-phase24.md",
        tests=("tests/test_vnext_preflight_report_phase22.py", "tests/test_v3_legacy_runtime.py"),
        checks=("runtime_command_boundary",),
    ),
    _item(
        "phase_25",
        "vNext preflight coverage expansion",
        "2026-07-05-vnext-preflight-coverage-phase25.md",
        tests=("tests/test_vnext_preflight_report_phase22.py",),
        checks=("preflight_coverage_expansion",),
    ),
    _item(
        "phase_26",
        "vNext coverage matrix",
        "2026-07-05-vnext-coverage-matrix-phase26.md",
        tests=("tests/test_vnext_preflight_report_phase22.py",),
        checks=("vnext_coverage",),
    ),
)


def _percent(count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round((count / total) * 100.0, 1)


def _json_safe(value: object) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False, default=str))
