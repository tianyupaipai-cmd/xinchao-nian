"""Read-only retrieval evaluation helpers.

Cases name the bucket IDs that should be returned for a query.  The evaluator
never touches buckets, so it can be run against a real vault before changing
weights, tokenization, or embedding models.
"""

from __future__ import annotations

from typing import Any


def normalize_cases(payload: Any) -> list[dict[str, Any]]:
    """Validate JSON-compatible retrieval cases and normalize optional fields."""
    if isinstance(payload, dict):
        payload = payload.get("cases")
    if not isinstance(payload, list) or not payload:
        raise ValueError("evaluation input must contain a non-empty 'cases' list")

    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(payload, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"case {index} must be an object")
        query = str(raw.get("query") or "").strip()
        expected = raw.get("expected_ids")
        if isinstance(expected, str):
            expected = [expected]
        if not query:
            raise ValueError(f"case {index} has an empty query")
        if not isinstance(expected, list) or not expected:
            raise ValueError(f"case {index} must provide expected_ids")
        expected_ids = [str(item).strip() for item in expected if str(item).strip()]
        if not expected_ids:
            raise ValueError(f"case {index} must provide non-empty expected_ids")

        domain = raw.get("domain")
        if isinstance(domain, str):
            domain_filter = [part.strip() for part in domain.split(",") if part.strip()]
        elif isinstance(domain, list):
            domain_filter = [str(part).strip() for part in domain if str(part).strip()]
        elif domain is None:
            domain_filter = []
        else:
            raise ValueError(f"case {index} domain must be a string or list")

        normalized.append({
            "name": str(raw.get("name") or f"case-{index}"),
            "query": query,
            "expected_ids": expected_ids,
            "domain_filter": domain_filter,
        })
    return normalized


async def evaluate_cases(
    bucket_manager: Any,
    cases: list[dict[str, Any]],
    *,
    top_k: int = 5,
    vector_scores_by_query: dict[str, dict[str, float]] | None = None,
) -> dict[str, Any]:
    """Evaluate Hit@K, Recall@K, and MRR against a BucketManager-like object."""
    top_k = max(1, int(top_k))
    vectors = vector_scores_by_query or {}
    details: list[dict[str, Any]] = []
    hits = 0
    recall_sum = 0.0
    reciprocal_rank_sum = 0.0

    for case in cases:
        expected = set(case["expected_ids"])
        results = await bucket_manager.search(
            case["query"],
            limit=top_k,
            domain_filter=case.get("domain_filter") or None,
            vector_scores=vectors.get(case["query"], {}),
        )
        result_ids = [str(item.get("id") or "") for item in results[:top_k]]
        found = [bucket_id for bucket_id in result_ids if bucket_id in expected]
        first_rank = next(
            (rank for rank, bucket_id in enumerate(result_ids, start=1) if bucket_id in expected),
            0,
        )
        hit = bool(found)
        recall = len(set(found)) / len(expected)
        reciprocal_rank = 1.0 / first_rank if first_rank else 0.0
        hits += int(hit)
        recall_sum += recall
        reciprocal_rank_sum += reciprocal_rank
        details.append({
            "name": case["name"],
            "query": case["query"],
            "expected_ids": sorted(expected),
            "result_ids": result_ids,
            "hit": hit,
            "recall": round(recall, 6),
            "first_relevant_rank": first_rank or None,
            "reciprocal_rank": round(reciprocal_rank, 6),
        })

    count = len(cases)
    return {
        "case_count": count,
        "top_k": top_k,
        "hit_rate": round(hits / count, 6) if count else 0.0,
        "mean_recall": round(recall_sum / count, 6) if count else 0.0,
        "mrr": round(reciprocal_rank_sum / count, 6) if count else 0.0,
        "cases": details,
    }


__all__ = ["normalize_cases", "evaluate_cases"]
