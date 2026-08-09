"""
========================================
tools/breath/catalog.py — catalog 目录模式（省 token 的记忆总览）
========================================

用途：开新对话时先花极少的 token 看一眼「我都记得哪些事」，再用
breath(query=...) 精准拉取需要的记忆——代替把全部记忆一股脑塞进上下文。

关键行为：
- 只读元数据（bucket_mgr.list_all），0 次 LLM/embedding 调用
- 每桶一行：名称 | 域 | 重要度，按重要度降序
- 按类型分区（固化/动态/feel/plan/letter），区头带数量
- 可选 domain 过滤（逗号分隔，OR 命中）

不做什么（边界）：
- 不返回正文、不算权重分、不触发衰减/浮现逻辑——那些是其他分支的事
- 不做 token 截断：目录本身就是最省形态，全量列出才有目录的意义
========================================
"""

from .. import _runtime as rt

# 类型 → (区头, 排序位)。未知类型归入动态区兜底。
_SECTIONS = [
    ("permanent", "固化"),
    ("dynamic", "动态"),
    ("feel", "feel"),
    ("plan", "plan"),
    ("letter", "letter"),
]


async def surface_catalog(domain_filter: list[str] | None = None) -> str:
    """返回全部记忆桶的紧凑目录。每桶一行：名称 | 域 | 重要度。"""
    try:
        buckets = await rt.bucket_mgr.list_all(include_archive=False)
    except Exception as e:
        return f"获取记忆目录失败: {e}"

    if not buckets:
        return "记忆库为空。"

    grouped: dict[str, list[tuple[int, str]]] = {key: [] for key, _ in _SECTIONS}
    for b in buckets:
        meta = b.get("metadata", {})
        domains = [d for d in (meta.get("domain") or []) if d]
        if domain_filter and not any(d in domain_filter for d in domains):
            continue
        try:
            imp = int(meta.get("importance") or 0)
        except (TypeError, ValueError):
            imp = 0
        name = meta.get("name") or b["id"]
        pin_mark = "📌" if (meta.get("pinned") or meta.get("protected")) else ""
        line = f"{pin_mark}{name} | {','.join(domains) or '未分类'} | {imp}"
        btype = meta.get("type")
        key = btype if btype in grouped else "dynamic"
        grouped[key].append((imp, line))

    total = sum(len(v) for v in grouped.values())
    if total == 0:
        return "没有匹配 domain 过滤的记忆桶。"

    parts = [
        f"=== 记忆目录（{total} 桶）===",
        "先看目录定位，再 breath(query=...) 精准拉取正文。",
    ]
    for key, label in _SECTIONS:
        rows = grouped[key]
        if not rows:
            continue
        rows.sort(key=lambda t: t[0], reverse=True)
        parts.append(f"--- {label}（{len(rows)}）---")
        parts.extend(line for _, line in rows)
    return "\n".join(parts)
