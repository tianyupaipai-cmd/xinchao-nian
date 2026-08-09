"""Privacy-preserving erasure tools.

All operations accept a bucket ID and return metadata-only status text. Memory
content is never accepted as input, logged, or returned.
"""

import re

from .. import _runtime as rt


_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_REASON_MAX = 500


def _normalize_id(bucket_id: str) -> str:
    value = str(bucket_id or "").strip()
    if not _ID_PATTERN.fullmatch(value):
        raise ValueError("id 必须是 1–128 位字母、数字、点、下划线或连字符。")
    return value


def _normalize_reason(reason: str) -> str:
    value = " ".join(str(reason or "").split()).strip()
    if not value:
        raise ValueError("reason 不能为空。")
    if len(value) > _REASON_MAX:
        raise ValueError(f"reason 不能超过 {_REASON_MAX} 个字符。")
    return value


async def forget_core(bucket_id: str, reason: str) -> str:
    try:
        bucket_id = _normalize_id(bucket_id)
        reason = _normalize_reason(reason)
    except ValueError as exc:
        return str(exc)
    if rt.mark_op:
        rt.mark_op("forget")
    rt.record_v3_tool_event(
        "forget",
        {"bucket_id": bucket_id, "reason_length": len(reason)},
    )
    success = await rt.bucket_mgr.delete(bucket_id, reason=reason)
    if not success:
        return f"未找到可软删除的记忆 ID: {bucket_id}"
    return f"已软删除记忆 ID: {bucket_id}。正文保留，但不会再参与 breath、dream、trace 或 feel。"


async def restore_core(bucket_id: str) -> str:
    try:
        bucket_id = _normalize_id(bucket_id)
    except ValueError as exc:
        return str(exc)
    if rt.mark_op:
        rt.mark_op("restore")
    rt.record_v3_tool_event("restore", {"bucket_id": bucket_id})
    success = await rt.bucket_mgr.restore(bucket_id)
    if not success:
        return f"未找到可恢复的软删除记忆 ID: {bucket_id}"
    return f"已恢复记忆 ID: {bucket_id}。"


async def purge_core(
    bucket_id: str,
    reason: str,
    confirm_id: str,
) -> str:
    try:
        bucket_id = _normalize_id(bucket_id)
        reason = _normalize_reason(reason)
        confirm_id = _normalize_id(confirm_id)
    except ValueError as exc:
        return str(exc)
    if confirm_id != bucket_id:
        return "拒绝硬删除：confirm_id 必须与 id 完全一致。"
    if rt.mark_op:
        rt.mark_op("purge")
    rt.record_v3_tool_event(
        "purge",
        {
            "bucket_id": bucket_id,
            "confirm_match": True,
            "reason_length": len(reason),
        },
    )
    invalidator = getattr(rt.dehydrator, "invalidate_cache", None)
    success = await rt.bucket_mgr.purge(
        bucket_id,
        reason,
        content_cache_invalidator=invalidator if callable(invalidator) else None,
    )
    if not success:
        return (
            f"硬删除未执行: {bucket_id}。目标必须先经过 forget 软删除，"
            "且所有派生存储清理必须成功。"
        )
    return f"已硬删除记忆 ID: {bucket_id}。该操作不可通过 restore 撤销。"
