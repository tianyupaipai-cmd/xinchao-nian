"""
========================================
tools/dream/candidates.py — 候选桶筛选 + 软上限
========================================

dream 的第一步：从全量桶里筛出「过去 window_hours 内有变动的表层
动态桶」，超过 40 个时按 calculate_score 截断，避免一次涌进来太多
炸上下文。

关键行为：
- 排除 permanent / feel / plan / letter / pinned / protected
- 任一 last_active 或 created 在窗口内即纳入
- 默认按 last_active 倒序，让最新的修改排前面
- 软上限 40，超了就改按 decay_engine 权重排序后截断

不做什么（边界）：
- 不做 dehydrate；返回原桶 dict 由 output.py 渲染
- 不调 LLM

对外暴露：collect_candidates(all_buckets, window_hours) → list[dict]
========================================
"""

from datetime import datetime, timedelta

from .. import _runtime as rt
from utils import parse_iso_datetime

DREAM_MAX_CANDIDATES = 40


def _metadata_timestamp(meta: dict) -> float:
    value = meta.get("last_active") or meta.get("created", "")
    try:
        return parse_iso_datetime(value).timestamp()
    except (ValueError, TypeError, OSError):
        return 0.0


def collect_core_context(all_buckets: list) -> list:
    core = [
        b for b in all_buckets
        if (
            b["metadata"].get("pinned", False)
            or b["metadata"].get("protected", False)
            or b["metadata"].get("type") == "permanent"
        )
        and b["metadata"].get("type") not in ("letter", "self", "i")
        and not b["metadata"].get("dont_surface", False)
    ]
    core.sort(
        key=lambda b: (
            int(b["metadata"].get("importance") or 0),
            _metadata_timestamp(b["metadata"]),
            b.get("id", ""),
        ),
        reverse=True,
    )
    return core[:20]


def collect_candidates(all_buckets: list, window_hours: int) -> list:
    candidates = [
        b for b in all_buckets
        if b["metadata"].get("type") not in ("permanent", "feel", "plan", "letter", "self", "i")
        and not b["metadata"].get("pinned", False)
        and not b["metadata"].get("protected", False)
        and not b["metadata"].get("dont_surface", False)
    ]
    cutoff = datetime.now() - timedelta(hours=window_hours)

    def _within_window(meta: dict) -> bool:
        for key in ("last_active", "created"):
            ts = meta.get(key, "")
            if not ts:
                continue
            try:
                if parse_iso_datetime(ts) >= cutoff:
                    return True
            except (ValueError, TypeError):
                continue
        return False

    recent = [b for b in candidates if _within_window(b["metadata"])]
    recent.sort(key=lambda b: _metadata_timestamp(b["metadata"]), reverse=True)
    if len(recent) > DREAM_MAX_CANDIDATES:
        recent.sort(
            key=lambda b: rt.decay_engine.calculate_score(b["metadata"]),
            reverse=True,
        )
        recent = recent[:DREAM_MAX_CANDIDATES]
    return recent
