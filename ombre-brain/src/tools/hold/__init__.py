"""
========================================
tools/hold/__init__.py — hold 工具入口
========================================

hold 是「我把这件事/这个感受存进我的记忆」。这个文件按入参把请求
路由到三种分支：feel（写第一人称感受）、pinned（钉为永久核心准则）、
core（普通存入 + 自动合并）。

关键行为：
- null-safe 兜底；先做 content / 字节上限校验，再分支
- feel=True / pinned=True 是互斥分支，否则走 core
- core 写完后 fire-and-forget 触发 plan 自动闭环 + 疑似重复扫描

不做什么（边界）：
- 不在这里做 LLM 打标，分支模块负责
- 不返回结构化数据，统一返回供模型阅读的中文短句

对外暴露：dispatch(content, tags, importance, pinned, feel, source_bucket,
                   valence, arousal, why_remembered, meaning, media) → str
========================================
"""

from typing import Optional

from .. import _runtime as rt
from .._common import (
    check_content_size,
    check_metadata_size,
    enforce_high_importance_quota,
    enforce_pinned_quota,
)
from .feel import store_feel
from .pinned import store_pinned
from .core import store_core
from ..write_admission import decide_write, default_ledger_path


async def dispatch(
    content: str,
    tags: Optional[str] = "",
    importance: Optional[int] = 5,
    pinned: Optional[bool] = False,
    feel: Optional[bool] = False,
    source_bucket: Optional[str] = "",
    valence: Optional[float] = -1,
    arousal: Optional[float] = -1,
    why_remembered: Optional[str] = "",
    meaning: Optional[str] = "",
    media: Optional[list] = None,
    auto: Optional[bool] = False,
    source: Optional[str] = "",
) -> str:
    content = "" if content is None else str(content)
    if tags is None:
        tags = ""
    if importance is None:
        importance = 5
    if pinned is None:
        pinned = False
    if feel is None:
        feel = False
    if source_bucket is None:
        source_bucket = ""
    if valence is None:
        valence = -1
    if arousal is None:
        arousal = -1
    if why_remembered is None:
        why_remembered = ""
    why_remembered = str(why_remembered).strip()[:500]
    if meaning is None:
        meaning = ""
    meaning = str(meaning).strip()
    if media is not None and not isinstance(media, list):
        media = None
    auto = bool(auto)
    source = "" if source is None else str(source).strip()[:80]
    try:
        importance = int(importance)
    except (TypeError, ValueError, OverflowError):
        importance = 5
    try:
        valence = float(valence)
    except (TypeError, ValueError, OverflowError):
        valence = -1
    try:
        arousal = float(arousal)
    except (TypeError, ValueError, OverflowError):
        arousal = -1

    metadata_err = check_metadata_size(
        tags=tags,
        source_bucket=source_bucket,
        why_remembered=why_remembered,
        meaning=meaning,
    )
    if metadata_err:
        return metadata_err
    if rt.mark_op:
        rt.mark_op("hold")
    rt.record_v3_tool_event("hold", {
        "content_length": len(content or ""),
        "tags": tags,
        "importance": importance,
        "pinned": pinned,
        "feel": feel,
        "source_bucket": source_bucket,
        "valence": valence,
        "arousal": arousal,
        "why_remembered_length": len(why_remembered or ""),
        "auto": auto,
        "source": source,
    })
    await rt.decay_engine.ensure_started()

    if not content or not content.strip():
        return "内容为空，无法存储。"

    err = check_content_size(content)
    if err:
        return err

    # importance 越界 clamp 由 bucket_manager 接管（OB-W001 自动 push 到 channel）；
    # 这里仅做一次软 clamp 便于配额判断。
    importance = max(1, min(10, importance))

    admission = decide_write(
        content,
        auto=auto,
        source=source,
        importance=importance,
        pinned=bool(pinned),
        why_remembered=why_remembered,
        meaning=meaning,
        ledger_path=default_ledger_path(rt.config) if auto else None,
    )
    if not admission.allowed:
        if admission.reason == "technical_only":
            return "自动写入已拒绝：纯技术内容不进入 Ombre Brain。"
        return (
            "自动候选暂未写入长期记忆；可由顾川/小雨手动 hold 直接保存，"
            "或等待再次出现。"
        )

    # pinned 配额检查（OB-W004 软警告 / OB-I002 自动退出）
    if pinned and not feel:
        pinned = await enforce_pinned_quota(True)

    # importance≥9 配额检查（OB-W003 软警告 / OB-I001 自动降级）
    if not pinned and not feel:
        importance = await enforce_high_importance_quota(importance)

    # valence/arousal 越界回退到自动打标（OB-W002 由 bucket_manager 在 clamp 时 push；
    # 这里的 -1 咨兵语义是"她/他未传"，越界则忽略，让 LLM analyze 决定）
    if valence != -1 and not (0 <= valence <= 1):
        try:
            try:
                from errors import push_warning  # type: ignore
            except ImportError:
                from ..errors import push_warning  # type: ignore
            push_warning("OB-W002", f"hold 入参 valence={valence} 越界，已忽略，回退到自动打标")
        except Exception:
            pass
        valence = -1
    if arousal != -1 and not (0 <= arousal <= 1):
        try:
            try:
                from errors import push_warning  # type: ignore
            except ImportError:
                from ..errors import push_warning  # type: ignore
            push_warning("OB-W002", f"hold 入参 arousal={arousal} 越界，已忽略，回退到自动打标")
        except Exception:
            pass
        arousal = -1

    if isinstance(tags, list):
        extra_tags = [str(t).strip() for t in tags if t]
    else:
        extra_tags = [t.strip() for t in str(tags).split(",") if t.strip()]

    # 所有越界/配额提醒走统一 warnings channel；server.py _with_notice 末尾自动追加。
    # 这里返回值只承载业务正文。

    if feel:
        if not source_bucket or not source_bucket.strip():
            return "feel 必须指向一条原始记忆（source_bucket 不能为空）。请先用 breath(query=...) 找到那条桶的 bucket_id，再传入 source_bucket=id。"
        result = await store_feel(
            content=content,
            extra_tags=extra_tags,
            valence=valence,
            arousal=arousal,
            source_bucket=source_bucket,
            why_remembered=why_remembered,
            meaning=meaning,
            media=media,
        )
        return result

    if pinned:
        result = await store_pinned(
            content=content,
            extra_tags=extra_tags,
            valence=valence,
            arousal=arousal,
            why_remembered=why_remembered,
            meaning=meaning,
            media=media,
        )
        return result

    result = await store_core(
        content=content,
        extra_tags=extra_tags,
        importance=importance,
        valence=valence,
        arousal=arousal,
        why_remembered=why_remembered,
        meaning=meaning,
        media=media,
    )
    return result
