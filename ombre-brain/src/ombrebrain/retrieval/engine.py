from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Iterable

from ombrebrain.retrieval.planner import RetrievalPlan


@dataclass(frozen=True)
class RetrievalEngine:
    trace_version: str = "v2.4.0.retrieval.trace.v1"

    @classmethod
    def default(cls) -> "RetrievalEngine":
        return cls()

    def trace(self, plan: RetrievalPlan, candidates: Iterable[dict[str, Any]] = ()) -> dict[str, Any]:
        candidate_list = tuple(_json_safe(candidate) for candidate in candidates)
        return _json_safe(
            {
                "trace_version": self.trace_version,
                "query": plan.intent.query,
                "operation": plan.intent.operation,
                "selected_channels": list(plan.channels),
                "stage_count": len(plan.stages),
                "stages": [stage.to_dict() for stage in plan.stages],
                "candidate_count": len(candidate_list),
                "candidate_ids": [str(candidate.get("id", "")) for candidate in candidate_list if "id" in candidate],
            }
        )


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False, default=str))
