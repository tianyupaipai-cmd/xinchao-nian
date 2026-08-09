"""
========================================
tools/breath/__init__.py — breath 工具的总入口与分支调度
========================================

breath 是「我睁眼看看自己记得什么」。这个文件根据参数把请求路由到
五个分支文件之一：

- catalog.py：catalog=True → 目录模式（每桶一行元数据，0 LLM，最省 token）
- feel.py：domain="feel"（或 tags 含 feel/__feel__）→ 拉所有 feel 桶
- importance.py：importance_min >= 1 → 跳过语义，按 importance 拉前 20
- surface.py：query 为空 → 浮现模式（pinned + 加权采样未解决桶 + passive）
- search.py：有 query → 检索模式（关键词 + 向量双通道 + 随机漂浮）

关键行为：
- 入口 dispatch() 做参数 null-safe 兜底、token/result 上限归一化、
  tags/domain 解析，再交给具体分支函数
- 不在这里做实际取桶/调 LLM 的工作

不做什么（边界）：
- 不直接处理 embedding 调用，全部下放到检索分支
- 正文渲染统一走 _verbatim.py，不进入 dehydrator
- 不做权限校验，MCP 调用方默认是模型自身

对外暴露：dispatch(query, max_tokens, domain, valence, arousal, max_results,
                   importance_min, tags, catalog) → str
========================================
"""

from typing import Optional

from .. import _runtime as rt
from .._common import check_metadata_size, check_query_size
from .catalog import surface_catalog
from .feel import surface_feels
from .importance import surface_by_importance
from .surface import surface_default
from .search import surface_search


async def dispatch(
    query: Optional[str] = "",
    max_tokens: Optional[int] = 0,
    domain: Optional[str] = "",
    valence: Optional[float] = -1,
    arousal: Optional[float] = -1,
    max_results: Optional[int] = 0,
    importance_min: Optional[int] = -1,
    tags: Optional[str] = "",
    catalog: Optional[bool] = False,
) -> str:
    # --- Null-safe coercion ---
    query = "" if query is None else str(query)
    if max_tokens is None:
        max_tokens = 0
    domain = "" if domain is None else str(domain)
    if valence is None:
        valence = -1
    if arousal is None:
        arousal = -1
    if max_results is None:
        max_results = 0
    if importance_min is None:
        importance_min = -1
    tags = "" if tags is None else str(tags)
    if catalog is None:
        catalog = False

    query_err = check_query_size(query)
    if query_err:
        return query_err
    metadata_err = check_metadata_size(domain=domain, tags=tags)
    if metadata_err:
        return metadata_err

    if rt.mark_op:
        rt.mark_op("breath")
    rt.record_v3_tool_event("breath", {
        "query": query,
        "max_tokens": max_tokens,
        "domain": domain,
        "valence": valence,
        "arousal": arousal,
        "max_results": max_results,
        "importance_min": importance_min,
        "tags": tags,
        "catalog": catalog,
    })
    await rt.decay_engine.ensure_started()

    # --- catalog 目录模式：最先短路，0 LLM、只读元数据、每桶一行 ---
    # 开新窗省 token 的推荐姿势：先 breath(catalog=True) 看目录，
    # 再 breath(query=...) 精准拉取正文。
    if catalog:
        domain_filter = [d.strip() for d in domain.split(",") if d.strip()]
        return await surface_catalog(domain_filter=domain_filter or None)

    surfacing_cfg = rt.config.get("surfacing", {}) or {}
    default_results = int(surfacing_cfg.get("breath_max_results") or 20)
    default_tokens = int(surfacing_cfg.get("breath_max_tokens") or 10000)
    if max_results <= 0:
        max_results = default_results
    if max_tokens <= 0:
        max_tokens = default_tokens
    max_results = min(max_results, 50)
    max_tokens = min(max_tokens, 20000)

    # --- 解析 tags 过滤；feel/__feel__ 映射到 feel 通道 ---
    tag_filter = [t.strip() for t in tags.split(",") if t.strip()]
    if any(t in ("feel", "__feel__") for t in tag_filter):
        domain = "feel"
        tag_filter = [t for t in tag_filter if t not in ("feel", "__feel__")]

    # --- Feel 通道优先：即使无 query 也直接拉 feel ---
    if domain.strip().lower() == "feel":
        return await surface_feels(max_tokens=max_tokens)

    # --- importance_min 模式：跳过语义，按 importance 降序 ---
    if importance_min >= 1:
        return await surface_by_importance(
            importance_min=importance_min,
            max_tokens=max_tokens,
            tag_filter=tag_filter,
        )

    # --- 无 query：浮现模式 ---
    if not query or not query.strip():
        return await surface_default(
            max_results=max_results,
            max_tokens=max_tokens,
            tag_filter=tag_filter,
        )

    # --- 有 query：检索模式 ---
    return await surface_search(
        query=query,
        max_results=max_results,
        max_tokens=max_tokens,
        domain=domain,
        valence=valence,
        arousal=arousal,
        tag_filter=tag_filter,
    )
