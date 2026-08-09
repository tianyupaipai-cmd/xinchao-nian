"""
========================================
tools/breath/feel.py — feel 通道
========================================

走 breath(domain="feel") 或 breath(tags="feel") 时进入这里。返回我留下
过的所有 feel（按时间倒序），在 token 预算内逐字返回完整正文。

关键行为：
- 列出所有 type=feel 的桶，按 created 倒序
- 在 max_tokens 预算内逐条放全文，下一条放不下就整条省略
- 不截断、不折叠、不摘要任何 feel 正文

不做什么（边界）：
- 不做语义检索；feel 不通过 query 过滤（feel 数量本身就少）
- 不做 dehydrate 调用，feel 原文短，直接展示

对外暴露：surface_feels(max_tokens) → str
========================================
"""

from .. import _runtime as rt
from ._verbatim import render_stored_bucket


async def surface_feels(max_tokens: int) -> str:
    try:
        all_buckets = await rt.bucket_mgr.list_all(include_archive=False)
        feels = [b for b in all_buckets if b.get("metadata", {}).get("type") == "feel"]
        feels.sort(key=lambda b: b.get("metadata", {}).get("created", ""), reverse=True)
        if not feels:
            return "没有留下过 feel。"
        full_lines: list[str] = []
        used = 0
        omitted = 0
        for index, f in enumerate(feels):
            created = f["metadata"].get("created", "")
            full_entry, cost = render_stored_bucket(
                f,
                f"[{created}] [bucket_id:{f['id']}]",
            )
            if used + cost <= max_tokens:
                full_lines.append(full_entry)
                used += cost
            else:
                omitted = len(feels) - index
                break
        out = "=== 你留下的 feel（新→旧）===\n" + "\n---\n".join(full_lines)
        if omitted:
            out += f"\n\n另有 {omitted} 条 feel 因 token 预算不足未返回；正文未截断或摘要。"
        return out
    except Exception as e:
        rt.logger.error(f"Feel retrieval failed: {e}")
        return "读取 feel 失败。"
