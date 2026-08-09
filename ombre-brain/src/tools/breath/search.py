"""
========================================
tools/breath/search.py — 有 query 的检索模式
========================================

走 breath(query=...) 时进入这里。一次向量查询与 bucket_manager 的
关键词/BM25 检索融合，命中后逐字返回桶正文并套 token 预算。

关键行为：
- domain/valence/arousal 作为过滤参数传给 bucket_mgr.search
- embedding 未配置/未启用/调用失败时明确提示并继续关键词/BM25 检索
- 向量通道阈值 sim>=0.65；domain/tags/type 过滤与关键词通道完全一致
- 命中正文不经过 LLM 摘要、改写或压缩，直接返回当前存储的 content
- 命中后调 touch()，但不修改本次返回的正文或元数据
- 检索结果 < 3 时 40% 概率从低权重旧桶里随机漂出 1-3 条「忽然想起来」
- 命中 0 条时回 webhook 报空，并给出可操作的引导文案

不做什么（边界）：
- 不返回 feel/plan/letter（专用通道有自己的入口）
- pinned/protected/permanent 仍可被检索（也是记忆，只是同时在浮现模式置顶）
- dont_surface=True 在检索中保留——主动遗忘只限制无参浮现

对外暴露：surface_search(query, max_results, max_tokens, domain, valence,
                          arousal, tag_filter) → str
========================================
"""

import asyncio
from ombrebrain.policy.surfacing import SurfacePolicyVM
from .. import _runtime as rt
from ._verbatim import render_stored_bucket
from .evidence import admit_direct_memory

_SURFACE_POLICY = SurfacePolicyVM.default()

_VECTOR_QUERY_TOPK = 50

_SEMANTIC_DISABLED_NOTE = "[检索降级：语义索引暂不可用，本次仅使用关键词/BM25。]"
_BUDGET_NOTICE = "[token 预算不足：命中的下一条记忆未被截断或摘要，请提高 max_tokens 后重试。]"


def _bucket_has_tags(meta: dict, tag_filter: list) -> bool:
    if not tag_filter:
        return True
    bucket_tags = set(meta.get("tags", []) or [])
    return all(t in bucket_tags for t in tag_filter)


def _can_surface_search(bucket: dict) -> bool:
    return _SURFACE_POLICY.evaluate_bucket(bucket, mode="search").allowed


async def _semantic_scores(query: str, top_k: int) -> tuple[dict[str, float], str]:
    """Run the vector query once and return scores plus an optional notice."""
    engine = rt.embedding_engine
    if not engine or not getattr(engine, "enabled", False):
        rt.logger.warning("breath semantic search unavailable; using keyword/BM25 only")
        return {}, _SEMANTIC_DISABLED_NOTE

    try:
        strict_search = getattr(engine, "search_similar_strict", None)
        if callable(strict_search):
            pairs = await strict_search(query, top_k=top_k)
        else:
            pairs = await engine.search_similar(query, top_k=top_k)
        return {bucket_id: float(score) for bucket_id, score in pairs}, ""
    except Exception as exc:
        rt.logger.warning(
            f"breath semantic search failed; using keyword/BM25 only: "
            f"{type(exc).__name__}: {exc}"
        )
        return {}, _SEMANTIC_DISABLED_NOTE


async def surface_search(
    query: str,
    max_results: int,
    max_tokens: int,
    domain: str,
    valence: float,
    arousal: float,
    tag_filter: list,
) -> str:
    domain_filter = [d.strip() for d in domain.split(",") if d.strip()] or None
    q_valence = valence if 0 <= valence <= 1 else None
    q_arousal = arousal if 0 <= arousal <= 1 else None

    # A full bucket id is an address, not a semantic query.  Resolve it before
    # embedding/BM25 work so callers can reliably read the on-disk source text
    # immediately before trace(content=...) without an LLM or derived index in
    # the path.  Archived/deleted and dedicated bucket types keep the same
    # visibility boundary as ordinary search.
    exact_id = query.strip()
    try:
        exact_bucket = await rt.bucket_mgr.get(exact_id)
    except Exception as exc:
        rt.logger.warning(
            f"breath exact bucket lookup failed; continuing with search: "
            f"{type(exc).__name__}: {exc}"
        )
        exact_bucket = None
    if exact_bucket:
        meta = exact_bucket.get("metadata", {}) or {}
        is_archived = meta.get("type") == "archived" or bool(meta.get("deleted_at"))
        if (
            not is_archived
            and meta.get("type") not in ("feel", "plan", "letter")
            and _can_surface_search(exact_bucket)
            and _bucket_has_tags(meta, tag_filter)
        ):
            rendered, entry_tokens = render_stored_bucket(
                exact_bucket,
                f"[exact_bucket_id:true] [bucket_id:{exact_bucket['id']}]",
            )
            if entry_tokens > max_tokens:
                return _BUDGET_NOTICE
            asyncio.create_task(
                rt.bucket_mgr.touch_many([exact_bucket["id"]], ripple=False)
            )
            if rt.fire_webhook:
                await rt.fire_webhook(
                    "breath",
                    {"mode": "exact_id", "matches": 1, "chars": len(rendered)},
                )
            return rendered

    vector_scores, semantic_notice = await _semantic_scores(
        query, top_k=max(max_results, _VECTOR_QUERY_TOPK)
    )

    try:
        matches = await rt.bucket_mgr.search(
            query,
            limit=max(max_results, 20),
            domain_filter=domain_filter,
            query_valence=q_valence,
            query_arousal=q_arousal,
            vector_scores=vector_scores,
        )
    except Exception as e:
        rt.logger.error(f"Search failed / 检索失败: {e}")
        return "检索过程出错，请稍后重试。"

    admitted = []
    rejected_reasons: dict[str, int] = {}
    for bucket in matches:
        if (
            not _can_surface_search(bucket)
            or bucket["metadata"].get("type") in ("feel", "plan", "letter")
        ):
            continue
        admission = admit_direct_memory(
            query,
            bucket,
            semantic_score=vector_scores.get(bucket["id"]),
        )
        if admission.allowed:
            admitted.append(bucket)
        else:
            rejected_reasons[admission.reason] = (
                rejected_reasons.get(admission.reason, 0) + 1
            )
    if rejected_reasons:
        rt.logger.info(
            "breath conservative admission rejected candidates: %s",
            rejected_reasons,
        )
    matches = admitted
    matches = [b for b in matches if _bucket_has_tags(b["metadata"], tag_filter)]
    matches = matches[:max_results]

    results = []
    token_used = 0
    budget_blocked = False
    touched_ids: list = []   # 性能 P2：浮现后统一在后台 touch，不在响应路径逐条 await
    for bucket in matches:
        meta = bucket["metadata"]
        bucket_id = bucket["id"]
        is_core = meta.get("pinned") or meta.get("protected") or meta.get("type") == "permanent"
        if is_core:
            header = f"📌 [核心准则] [bucket_id:{bucket_id}]"
        elif bucket.get("vector_match"):
            header = f"[语义关联] [bucket_id:{bucket_id}]"
        else:
            header = f"[bucket_id:{bucket_id}]"
        rendered, entry_tokens = render_stored_bucket(bucket, header)
        if token_used + entry_tokens > max_tokens:
            budget_blocked = True
            break
        results.append(rendered)
        token_used += entry_tokens
        touched_ids.append(bucket_id)

    # 性能 P2：把 touch 移出响应路径 —— 浮现完的桶在后台一次性更新激活，
    # ripple=False 跳过读全库的时间涟漪。响应不再等这些写盘/涟漪。
    if touched_ids:
        asyncio.create_task(rt.bucket_mgr.touch_many(touched_ids, ripple=False))

    if not results:
        if budget_blocked:
            return f"{semantic_notice}\n{_BUDGET_NOTICE}" if semantic_notice else _BUDGET_NOTICE
        if rt.fire_webhook:
            await rt.fire_webhook("breath", {"mode": "empty", "matches": 0})
        empty_text = (
            f"没有匹配到「{query}」相关的记忆。\n"
            "可以换个关键词试试，或不带 query 看当下权重池；feel 用 breath(domain=\"feel\")，信件用 letter_read。"
        )
        return f"{semantic_notice}\n{empty_text}" if semantic_notice else empty_text

    final_text = "\n---\n".join(results)
    notices = []
    if semantic_notice:
        notices.append(semantic_notice)
    if budget_blocked:
        notices.append(_BUDGET_NOTICE)
    if notices:
        final_text = "\n".join(notices + [final_text])
    if rt.fire_webhook:
        await rt.fire_webhook("breath", {"mode": "ok", "matches": len(matches), "chars": len(final_text)})
    return final_text
