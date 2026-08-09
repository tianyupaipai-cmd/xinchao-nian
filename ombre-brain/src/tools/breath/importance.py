"""
========================================
tools/breath/importance.py — importance_min 模式
========================================

走 breath(importance_min=N) 时进入这里。跳过语义检索，按 importance
分层拉标过的核心事项（最多 20 条），让模型一次性扫一眼自己
认定为「重要」的桶。

关键行为：
- 列出所有非 feel/plan/letter、未主动遗忘、且 importance >= 阈值 的桶
- tags 过滤同样生效（AND）
- 按 importance 降序；若高分桶超过 20 条，仍保留阈值档位的最近更新桶
- 截到 20 条后逐字返回存储正文，再塞进 max_tokens 预算

不做什么（边界）：
- 不做向量检索（这是「按重要度批量拉」而不是「找相似」）
- 不主动 touch（浮现行为不应重置衰减计时器）

对外暴露：surface_by_importance(importance_min, max_tokens, tag_filter) → str
========================================
"""

from .. import _runtime as rt
from ._verbatim import render_stored_bucket

_BUDGET_NOTICE = "token 预算不足：下一条重要记忆未被截断或摘要，请提高 max_tokens 后重试。"


def _bucket_has_tags(meta: dict, tag_filter: list) -> bool:
    if not tag_filter:
        return True
    bucket_tags = set(meta.get("tags", []) or [])
    return all(t in bucket_tags for t in tag_filter)


def _importance_of(bucket: dict) -> int:
    try:
        return int(bucket.get("metadata", {}).get("importance") or 0)
    except Exception:
        return 0


def _importance_sort_key(bucket: dict):
    meta = bucket.get("metadata", {}) or {}
    return (
        _importance_of(bucket),
        str(meta.get("last_active") or meta.get("created") or ""),
        str(bucket.get("id") or ""),
    )


def _select_importance_buckets(buckets: list[dict], importance_min: int, limit: int = 20) -> list[dict]:
    """Keep high-importance results useful even when one level fills the cap.

    The old behavior sorted all buckets by importance and cut the first 20.
    With many importance=10 buckets, a freshly traced 10→9 bucket could be
    hidden, making the update look stale. Reserve one recent bucket from each
    eligible importance level first, then fill the rest by normal ranking.
    """
    limit = max(1, int(limit or 20))
    ordered = sorted(buckets, key=_importance_sort_key, reverse=True)
    if len(ordered) <= limit:
        return ordered

    by_importance: dict[int, list[dict]] = {}
    for bucket in ordered:
        by_importance.setdefault(_importance_of(bucket), []).append(bucket)

    selected: list[dict] = []
    selected_ids: set[str] = set()

    def add(bucket: dict) -> None:
        bid = str(bucket.get("id") or "")
        if bid and bid not in selected_ids and len(selected) < limit:
            selected.append(bucket)
            selected_ids.add(bid)

    for imp in range(10, importance_min - 1, -1):
        choices = by_importance.get(imp)
        if choices:
            add(choices[0])
        if len(selected) >= limit:
            break

    for bucket in ordered:
        add(bucket)
        if len(selected) >= limit:
            break

    return sorted(selected, key=_importance_sort_key, reverse=True)


async def surface_by_importance(importance_min: int, max_tokens: int, tag_filter: list) -> str:
    try:
        all_buckets = await rt.bucket_mgr.list_all(include_archive=False)
    except Exception as e:
        return f"记忆系统暂时无法访问: {e}"
    filtered = [
        b for b in all_buckets
        if int(b.get("metadata", {}).get("importance") or 0) >= importance_min
        and b.get("metadata", {}).get("type") not in ("feel", "plan", "letter")
        and not b.get("metadata", {}).get("dont_surface", False)
        and _bucket_has_tags(b.get("metadata", {}), tag_filter)
    ]
    filtered = _select_importance_buckets(filtered, importance_min, limit=20)
    if not filtered:
        return f"没有重要度 >= {importance_min} 的记忆。"
    results = []
    token_used = 0
    budget_blocked = False
    for b in filtered:
        try:
            imp = b["metadata"].get("importance", 0)
            rendered, entry_tokens = render_stored_bucket(
                b,
                f"[importance:{imp}] [bucket_id:{b['id']}]",
            )
            if token_used + entry_tokens > max_tokens:
                budget_blocked = True
                break
            results.append(rendered)
            token_used += entry_tokens
        except Exception as e:
            rt.logger.warning(f"importance_min bucket processing failed: {e}")
    if not results:
        return _BUDGET_NOTICE if budget_blocked else "没有可以展示的记忆。"
    if budget_blocked:
        results.append(_BUDGET_NOTICE)
    return "\n---\n".join(results)
