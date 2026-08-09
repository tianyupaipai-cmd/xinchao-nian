"""
========================================
tools/grow/core.py — grow 长内容主路径（digest + merge）
========================================

长内容（≥30 字）走这里。先调 dehydrator.digest 把整段拆成 2~6 条
事件项，每条独立尝试 merge_or_create。

关键行为：
- digest 失败（API key 不可用）时直接 RuntimeError，不创建任何桶
- 逐条调 merge_or_create（grow 路径用 LLM merge，会压缩老+新）
- iter 2.0：每次 grow 调用生成一个 ``grow_batch_id``，同批次新建桶共享，
  source_tool 一律为 ``grow``；合并到的老桶不改 source_tool
- 单条失败不影响其他；按字节上限校验单条尺寸
- embedding 失败时桶正常创建，返回追加向量化降级警告
- 末尾 fire-and-forget 触发 plan 自动闭环（用整段原文做匹配）

不做什么（边界）：
- 不写 feel：grow 是事件归档，不是反思
- 不做 pinned 标记：grow 拆出来的事件桶都是 dynamic
- 不接受 why_remembered：grow 是整理，拆出来的每条桶就是事件本身，是 why 本身

对外暴露：grow_core(content) → str
========================================
"""

import asyncio
import uuid

from .. import _runtime as rt
from .._common import (
    merge_or_create,
    check_content_size,
    check_grow_items_payload,
    check_duplicate_for,
    check_plan_resolution,
)
from ..write_admission import decide_write, default_ledger_path


async def grow_core(content: str, *, auto: bool = False, source: str = "") -> str:
    try:
        items = await rt.dehydrator.digest(content)
    except Exception as e:
        rt.logger.error(f"Diary digest failed / 日记整理失败: {e}")
        raise RuntimeError(
            f"API key 未配置或调用失败，日记拆分无法完成，桶未创建。请检查 OMBRE_COMPRESS_API_KEY。（错误：{e}）"
        ) from e

    if not isinstance(items, list) or not items:
        return "内容为空或整理失败。"
    payload_err = check_grow_items_payload(items)
    if payload_err:
        rt.logger.warning(f"grow digest output rejected: {payload_err}")
        return payload_err

    # iter 2.0 来源追踪：同一次 grow 拆出的所有桶共享同一个 batch_id，
    # dashboard 可按 grow_batch_id 聚合显示「这次日记一共归档了哪些事件」。
    # 用 12 位 hex 与 bucket_id 长度对齐，加 g_ 前缀方便人眼区分。
    batch_id = f"g_{uuid.uuid4().hex[:12]}"

    results = []
    created = 0
    merged = 0
    embed_warnings = []

    for item in items:
        try:
            admission = decide_write(
                item.get("content", ""),
                auto=auto,
                source=source,
                importance=item.get("importance") or 5,
                ledger_path=default_ledger_path(rt.config) if auto else None,
            )
            if not admission.allowed:
                label = "技术内容拒绝" if admission.reason == "technical_only" else "自动候选待审"
                results.append(f"⏸️{item.get('name', '?')}（{label}）")
                continue
            size_err = check_content_size(item.get("content", ""))
            if size_err:
                results.append(f"⚠️{item.get('name', '?')}（{size_err}）")
                continue
            result_name, is_merged, embed_warn = await merge_or_create(
                content=item["content"],
                tags=item.get("tags") or [],
                importance=item.get("importance") or 5,
                domain=item.get("domain") or ["未分类"],
                valence=item.get("valence") or 0.5,
                arousal=item.get("arousal") or 0.3,
                name=item.get("name", ""),
                source_tool="grow",
                grow_batch_id=batch_id,
            )
            if embed_warn and embed_warn not in embed_warnings:
                embed_warnings.append(embed_warn)

            if is_merged:
                results.append(f"📎{result_name}")
                merged += 1
            else:
                results.append(f"📝{item.get('name', result_name)}")
                created += 1
                asyncio.create_task(check_duplicate_for(result_name, item["content"]))
        except Exception as e:
            rt.logger.warning(
                f"Failed to process diary item / 日记条目处理失败: "
                f"{item.get('name', '?')}: {e}"
            )
            results.append(f"⚠️{item.get('name', '?')}")

    asyncio.create_task(check_plan_resolution(content))
    summary = f"{len(items)}条|新{created}合{merged} batch:{batch_id}\n" + "\n".join(results)
    if embed_warnings:
        summary += f"\n⚠️ {embed_warnings[0]}"
    return summary


async def grow_items(
    items: list,
    *,
    auto: bool = False,
    source: str = "",
) -> str:
    """预拆分模式：上层 AI 已把长文拆成 N 条最终正文，直接逐字入库。

    与 grow_core 的关键差别（issue 的诉求）：
    - **不调 digest**：跳过廉价 LLM 的二次拆分+改写，正文一字不动（消除第二次失真）；
    - 每条只调 analyze() 打元数据（domain/valence/arousal/tags/name），不碰正文；
    - 合并走 raw_merge=True（原文追加，不 LLM 压缩老+新），消除第三次失真。
    存储沿用 grow 风格：共享 grow_batch_id，source_tool=grow，dashboard 仍可按批展示。
    """
    payload_err = check_grow_items_payload(items)
    if payload_err:
        return payload_err

    # 规整：接受字符串条目；也容忍 {"content": "..."} 形式，取其正文。空条目丢弃。
    clean: list[str] = []
    for it in items:
        if isinstance(it, str):
            s = it.strip()
        elif isinstance(it, dict):
            s = str(it.get("content", "")).strip()
        else:
            s = ""
        if s:
            clean.append(s)
    if not clean:
        return "items 为空或都不合法，未创建任何桶。"

    batch_id = f"g_{uuid.uuid4().hex[:12]}"
    results = []
    created = 0
    merged = 0
    embed_warnings = []

    metadata_fallback = False
    for content_str in clean:
        try:
            admission = decide_write(
                content_str,
                auto=auto,
                source=source,
                ledger_path=default_ledger_path(rt.config) if auto else None,
            )
            if not admission.allowed:
                label = "技术内容拒绝" if admission.reason == "technical_only" else "自动候选待审"
                results.append(f"⏸️（{label}）")
                continue
            size_err = check_content_size(content_str)
            if size_err:
                results.append(f"⚠️（{size_err}）")
                continue
            # 只打标，不改写正文；打标失败（如 API key 未配置）不应丢正文——
            # 落回本地中性元数据，与 hold 的降级行为保持一致（见 tools/hold/core.py）。
            try:
                meta = await rt.dehydrator.analyze(content_str)
            except Exception as e:
                metadata_fallback = True
                rt.logger.warning(
                    "grow items metadata analysis failed; preserving raw content with local defaults / "
                    f"grow items 打标失败，使用本地默认元数据并原样保存正文: {type(e).__name__}: {e}"
                )
                default_analysis = getattr(rt.dehydrator, "_default_analysis", None)
                meta = default_analysis() if callable(default_analysis) else {
                    "domain": ["未分类"], "valence": 0.5, "arousal": 0.3, "tags": [], "suggested_name": "",
                }
            result_name, is_merged, embed_warn = await merge_or_create(
                content=content_str,
                tags=meta.get("tags") or [],
                importance=5,
                domain=meta.get("domain") or ["未分类"],
                valence=meta.get("valence", 0.5),
                arousal=meta.get("arousal", 0.3),
                name=meta.get("suggested_name", ""),
                source_tool="grow",
                grow_batch_id=batch_id,
                raw_merge=True,  # 逐字追加，合并不压缩
            )
            if embed_warn and embed_warn not in embed_warnings:
                embed_warnings.append(embed_warn)
            if is_merged:
                results.append(f"📎{result_name}")
                merged += 1
            else:
                results.append(f"📝{result_name}")
                created += 1
                asyncio.create_task(check_duplicate_for(result_name, content_str))
        except Exception as e:
            rt.logger.warning(f"grow items 条目处理失败 / verbatim item failed: {e}")
            results.append("⚠️")

    asyncio.create_task(check_plan_resolution("\n".join(clean)))
    summary = f"{len(clean)}条(预拆分·逐字)|新{created}合{merged} batch:{batch_id}\n" + "\n".join(results)
    if embed_warnings:
        summary += f"\n⚠️ {embed_warnings[0]}"
    if metadata_fallback:
        summary += "\n⚠️ 打标 API 暂不可用：正文已逐字保存，未做任何压缩；元数据暂用本地中性值。"
    return summary
