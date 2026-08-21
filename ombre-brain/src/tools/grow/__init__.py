"""
========================================
tools/grow/__init__.py — grow 工具入口
========================================

grow 是「我把一段长内容整理进记忆」。短内容（<30 字）走 shortpath，
跳过 LLM 拆分省 API；长内容走 core，调 dehydrator.digest 拆成 2~6 条
独立事件桶。

关键行为：
- 入口做 content 校验
- 按 strip 后长度 < 30 字判断走哪个分支

不做什么（边界）：
- 不做 token 级别预算（grow 关心的是「拆几条」而不是「展示多少」）
- 不返回结构化数据，统一中文短句

对外暴露：dispatch(content) → str
========================================
"""

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Optional

from .. import _runtime as rt
from .._common import check_grow_input_size, check_grow_items_payload
from .shortpath import grow_shortpath
from .core import grow_core, grow_items
from ..write_admission import decide_write, default_ledger_path


# ---------- 重复提交去重（幂等重试）----------
# 场景：客户端（如 claude.ai 连接器）等不到 grow 返回先超时，但服务端其实已写入；
# 上层 AI 以为失败而重试，同一段日记被反复拆成新桶。这里按 (content/items, auto, source)
# 指纹记住最近一次成功结果，窗口内同样内容再来时直接返回上次结果、不再写入。
# 只缓存成功结果（失败必须能重试）；IO 出错时静默放行，绝不阻塞 grow 本身。
_DEDUPE_WINDOW_SECONDS = max(0, int(os.environ.get("OMBRE_GROW_DEDUPE_SECONDS", "21600") or 0))  # 默认 6h，0=关闭
_DEDUPE_MAX_ENTRIES = 200


def _dedupe_path() -> Path:
    cfg = rt.config if isinstance(rt.config, dict) else {}
    buckets_dir = Path(str(cfg.get("buckets_dir") or "buckets"))
    return buckets_dir / ".companion" / "grow-recent.json"


def grow_fingerprint(content: str, items: Optional[list], auto: bool, source: str) -> str:
    payload = json.dumps(
        {"c": (content or "").strip(), "i": items or [], "a": bool(auto), "s": source or ""},
        ensure_ascii=False, sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def is_grow_success(result: str) -> bool:
    """grow 的成功文案：长文带 batch:g_xxx；短文走 hold 路径有固定开头。失败文案都没有这两样。"""
    r = result or ""
    return "batch:" in r or r.startswith("短内容已按 hold 路径保存")


def _load_recent(path: Path, now: float) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items()
            if isinstance(v, dict) and now - float(v.get("at", 0)) < _DEDUPE_WINDOW_SECONDS}


def recent_grow_result(fp: str, *, path: Optional[Path] = None, now: Optional[float] = None) -> Optional[dict]:
    if _DEDUPE_WINDOW_SECONDS <= 0:
        return None
    now = time.time() if now is None else now
    path = path or _dedupe_path()
    return _load_recent(path, now).get(fp)


def remember_grow_result(fp: str, result: str, *, path: Optional[Path] = None, now: Optional[float] = None) -> None:
    if _DEDUPE_WINDOW_SECONDS <= 0 or not is_grow_success(result):
        return
    now = time.time() if now is None else now
    path = path or _dedupe_path()
    try:
        data = _load_recent(path, now)
        data[fp] = {"at": now, "result": result}
        if len(data) > _DEDUPE_MAX_ENTRIES:
            for k in sorted(data, key=lambda k: data[k]["at"])[: len(data) - _DEDUPE_MAX_ENTRIES]:
                data.pop(k, None)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except Exception as e:  # 去重是锦上添花，出错不许影响正常写入
        rt.logger and rt.logger.warning(f"grow dedupe ledger write failed: {e}")


def _dedupe_reply(hit: dict, now: float) -> str:
    minutes = max(0, int((now - float(hit.get("at", now))) // 60))
    return (
        f"（重复提交：同样的内容 {minutes} 分钟前已整理入库，本次未重复写入。"
        f"若确需再次导入，请修改内容或等待去重窗口过期。）\n上次结果：\n{hit.get('result', '')}"
    )



async def dispatch(
    content: str = "",
    items: Optional[list] = None,
    auto: Optional[bool] = False,
    source: Optional[str] = "",
) -> str:
    await rt.decay_engine.ensure_started()
    auto = bool(auto)
    source = "" if source is None else str(source).strip()[:80]
    fp = grow_fingerprint(content, items if isinstance(items, list) else None, auto, source)
    hit = recent_grow_result(fp)
    if hit:
        return _dedupe_reply(hit, time.time())

    # 预拆分模式：上层 AI 已拆好 N 条最终正文 → 逐字入库，跳过 digest 的二次改写。
    # 传了 items（非空列表）即走此路；不传则行为与旧版完全一致（向后兼容）。
    if isinstance(items, list) and len(items) > 0:
        err = check_grow_items_payload(items)
        if err:
            return err
        result = await grow_items(items, auto=auto, source=source)
        remember_grow_result(fp, result)
        return result

    if not content or not content.strip():
        return "内容为空，无法整理。"

    err = check_grow_input_size(content)
    if err:
        return err

    if len(content.strip()) < 30:
        admission = decide_write(
            content,
            auto=auto,
            source=source,
            ledger_path=default_ledger_path(rt.config) if auto else None,
        )
        if not admission.allowed:
            if admission.reason == "technical_only":
                return "自动写入已拒绝：纯技术内容不进入 Ombre Brain。"
            return "自动候选暂未写入；人工 grow/hold 可直接保存。"
        result = await grow_shortpath(content)
        remember_grow_result(fp, result)
        return result
    result = await grow_core(content, auto=auto, source=source)
    remember_grow_result(fp, result)
    return result
