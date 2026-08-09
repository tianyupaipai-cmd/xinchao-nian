from __future__ import annotations

from typing import Any

from ombrebrain.domain import AdvancedCommandBoundaryContract


def build_runtime_command_boundary_health(events: list[object], *, limit: int = 50) -> dict[str, Any]:
    recent_events = events[-limit:] if limit > 0 else events
    candidates = [event for event in recent_events if _is_boundary_candidate(event)]
    contract = AdvancedCommandBoundaryContract.default()
    reports: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    missing_receipts: list[dict[str, Any]] = []

    for event in candidates:
        metadata = dict(getattr(event, "metadata", {}) or {})
        boundary_error = metadata.get("command_boundary_error")
        if isinstance(boundary_error, dict):
            issues.append(
                {
                    "code": "command_boundary_metadata_error",
                    "message": str(boundary_error.get("error_message") or "command boundary metadata failed"),
                    "event": _event_summary(event),
                    "metadata": boundary_error,
                }
            )
            continue

        boundary = metadata.get("command_boundary")
        if not isinstance(boundary, dict):
            missing_receipts.append(_event_summary(event))
            continue

        receipt = boundary.get("receipt")
        if not isinstance(receipt, dict):
            issues.append(
                {
                    "code": "command_boundary_receipt_missing",
                    "message": "runtime command boundary metadata does not include a receipt",
                    "event": _event_summary(event),
                    "metadata": {},
                }
            )
            continue

        report = contract.evaluate_receipt(receipt).to_dict()
        reports.append(report)
        if not report.get("ok"):
            for issue in report.get("issues", []):
                issue_data = dict(issue)
                issue_data["event"] = _event_summary(event)
                issues.append(issue_data)

    status = "error" if issues else "warning" if missing_receipts else "ok"
    return {
        "ok": not issues,
        "status": status,
        "event_count": len(events),
        "scanned_event_count": len(recent_events),
        "candidate_event_count": len(candidates),
        "receipt_count": len(reports),
        "missing_receipt_count": len(missing_receipts),
        "invalid_receipt_count": len(
            {str(issue.get("event", {}).get("id", "")) for issue in issues if issue.get("event")}
        ),
        "reports": reports,
        "missing_receipts": missing_receipts,
        "issues": issues,
    }


def _is_boundary_candidate(event: object) -> bool:
    metadata = dict(getattr(event, "metadata", {}) or {})
    source_chain = tuple(str(part) for part in getattr(event, "source_chain", ()) or ())
    return (
        "command_boundary" in metadata
        or "command_boundary_error" in metadata
        or "command_plan" in metadata
        or source_chain[:1] in {("legacy_execution",), ("legacy_tool",)}
    )


def _event_summary(event: object) -> dict[str, Any]:
    metadata = dict(getattr(event, "metadata", {}) or {})
    command_plan = metadata.get("command_plan") if isinstance(metadata.get("command_plan"), dict) else {}
    return {
        "id": str(getattr(event, "id", "")),
        "source_chain": list(getattr(event, "source_chain", ()) or ()),
        "command_id": str(command_plan.get("command_id", "")),
        "command_kind": str(command_plan.get("command_kind", "")),
    }
