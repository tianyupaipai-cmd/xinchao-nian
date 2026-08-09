from __future__ import annotations

from dataclasses import dataclass

from ombrebrain.acceptance.contracts import (
    AcceptanceIssue,
    AcceptanceReport,
    CompatibilitySnapshot,
    LegacyCompatibilityContract,
)


@dataclass(frozen=True)
class FormalAcceptanceHarness:
    contract: LegacyCompatibilityContract

    @classmethod
    def default(cls) -> "FormalAcceptanceHarness":
        return cls(LegacyCompatibilityContract.default())

    def evaluate(self, snapshot: CompatibilitySnapshot | None = None) -> AcceptanceReport:
        observed = snapshot or CompatibilitySnapshot.from_contract(self.contract)
        issues: list[AcceptanceIssue] = []
        issues.extend(_missing("tool_name", self.contract.tool_names, observed.tool_names))
        issues.extend(_missing("dashboard_route", self.contract.dashboard_routes, observed.dashboard_routes))
        issues.extend(
            _missing(
                "bucket_markdown_field",
                self.contract.bucket_markdown_fields,
                observed.bucket_markdown_fields,
            )
        )
        issues.extend(_missing("protected_surface", self.contract.protected_surfaces, observed.protected_surfaces))
        return AcceptanceReport(
            ok=not issues,
            contract=self.contract,
            snapshot=observed,
            issues=tuple(issues),
        )


def _missing(kind: str, required: tuple[str, ...], observed: tuple[str, ...]) -> tuple[AcceptanceIssue, ...]:
    observed_set = set(observed)
    return tuple(
        AcceptanceIssue(
            code=f"missing_{kind}",
            message=f"legacy compatibility snapshot is missing required {kind}",
            value=value,
        )
        for value in required
        if value not in observed_set
    )
