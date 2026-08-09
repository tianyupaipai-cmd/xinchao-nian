"""
========================================
migration_engine.py — embedding 迁移引擎（2.0.3 新增）
========================================

切 embedding 后端（local ↔ api）时，需要把 embeddings.db 里所有 bucket 的向量
用新后端重算一遍。这个模块负责后台跑这件事：

- 备份 embeddings.db → embeddings.db.backup（只在第一次启动时）
- 把新向量先写入 embeddings.db.migrating，避免半截状态污染主表
- 全部跑完后 atomically swap：主 db 替成 .migrating 文件
- 单条失败跳过 + 记录到 failed_items[:50]，不中断整体
- 进度文件 _pending_migration_status.json，前端 3s 轮询
- 断点续传：_migration_checkpoint.json 记录已完成 id 集合
- 限速：每批 10 条，间隔 0.5s（避免本地推理打爆 CPU 或 API 限流）
- 失败时附最近 15 行 errors.jsonl，提示她/他「这是本地环境相关问题」

不做：
- 不做 bucket 迁移、桶文件重写
- 不切换 global embedding_engine —— 那是 server.py 调用方的事
- 不做配置写盘
========================================
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import threading
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Iterable

logger = logging.getLogger("ombre_brain.migration_engine")


# ---- 常量 ----

_STATUS_FILE_NAME = "_pending_migration_status.json"
_CHECKPOINT_FILE_NAME = "_migration_checkpoint.json"

# 每批 10 条，间隔 0.5s
BATCH_SIZE = 10
BATCH_INTERVAL_SEC = 0.5

# failed_items 上限（避免 status JSON 无限膨胀）
MAX_FAILED_ITEMS = 50

# 失败时附带的 errors.jsonl 末尾行数
TAIL_LOG_LINES = 15

# 进程级锁：同一时刻只允许一个迁移任务
_migration_lock = threading.Lock()
_migration_task: asyncio.Task | None = None
_v3_runtime: Any = None


def attach_v3_runtime(runtime) -> None:
    global _v3_runtime
    _v3_runtime = runtime


def get_v3_runtime():
    return _v3_runtime


# ============================================================
# 路径与状态
# ============================================================

def status_path_for(buckets_dir: str) -> str:
    log_dir = os.path.join(buckets_dir, ".logs")
    os.makedirs(log_dir, exist_ok=True)
    return os.path.join(log_dir, _STATUS_FILE_NAME)


def checkpoint_path_for(buckets_dir: str) -> str:
    log_dir = os.path.join(buckets_dir, ".logs")
    os.makedirs(log_dir, exist_ok=True)
    return os.path.join(log_dir, _CHECKPOINT_FILE_NAME)


def _empty_status() -> dict[str, Any]:
    return {
        "phase": "idle",      # idle | running | completed | failed
        "total": 0,
        "done": 0,
        "failed_count": 0,
        "current_id": "",
        "failed_items": [],
        "started_at": "",
        "finished_at": "",
        "target_backend": "",
        "target_model": "",
        "target_dim": 0,
        "message": "",
        "error": "",
        "tail_log": [],
    }


def read_status(status_path: str) -> dict[str, Any]:
    if not os.path.exists(status_path):
        return _empty_status()
    try:
        with open(status_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return _empty_status()
        return data
    except (OSError, json.JSONDecodeError):
        return _empty_status()


def write_status(status_path: str, status: dict[str, Any]) -> None:
    try:
        os.makedirs(os.path.dirname(status_path), exist_ok=True)
        tmp = status_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(status, f, ensure_ascii=False, indent=2)
        os.replace(tmp, status_path)
    except OSError as e:
        logger.warning(f"[migration] failed to write status: {e}")


def _read_checkpoint(path: str) -> set[str]:
    if not os.path.exists(path):
        return set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        done = data.get("done_ids", []) if isinstance(data, dict) else []
        return set(done) if isinstance(done, list) else set()
    except (OSError, json.JSONDecodeError):
        return set()


def _write_checkpoint(path: str, done_ids: Iterable[str]) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"done_ids": sorted(done_ids)}, f, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError as e:
        logger.warning(f"[migration] failed to write checkpoint: {e}")


def _tail_errors_log(buckets_dir: str, n: int = TAIL_LOG_LINES) -> list[str]:
    """读 errors.jsonl 末尾 n 行。失败返回空列表。"""
    candidates = [
        os.path.join(buckets_dir, ".logs", "errors.jsonl"),
        os.path.join(buckets_dir, "errors.jsonl"),
    ]
    for p in candidates:
        if not os.path.exists(p):
            continue
        try:
            with open(p, "r", encoding="utf-8") as f:
                lines = f.readlines()
            return [ln.rstrip("\n") for ln in lines[-n:]]
        except OSError:
            continue
    return []


# ============================================================
# 备份与提交
# ============================================================

def backup_db_once(db_path: str) -> str:
    """如果 .backup 不存在则备份 db_path，返回备份文件路径。

    已存在 .backup 则不重复备份（避免覆盖更早版本）。
    """
    backup = db_path + ".backup"
    if os.path.exists(backup):
        return backup
    if not os.path.exists(db_path):
        return backup
    shutil.copy2(db_path, backup)
    return backup


# ============================================================
# 迁移核心
# ============================================================

@dataclass
class MigrationConfig:
    """迁移参数。"""
    buckets_dir: str
    db_path: str
    target_backend: str          # 'local' | 'api'
    target_model: str
    target_dim: int
    # source/target engine 都已由调用方实例化好
    target_engine: Any           # EmbeddingEngine 实例（迁移目标）
    # bucket 内容来源：返回 list[(bucket_id, content)] 的 awaitable
    fetch_buckets: Callable[[], Awaitable[list[tuple[str, str]]]]


async def _run_migration(
    cfg: MigrationConfig,
    on_complete: Callable[[bool], None] | None = None,
) -> None:
    """实际跑迁移的协程。"""
    status_path = status_path_for(cfg.buckets_dir)
    ckpt_path = checkpoint_path_for(cfg.buckets_dir)

    # 1) 备份原 db
    try:
        backup_db_once(cfg.db_path)
    except Exception as e:
        write_status(status_path, {
            **_empty_status(),
            "phase": "failed",
            "error": f"backup failed: {type(e).__name__}: {e}",
            "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "message": "迁移未启动：备份 embeddings.db 失败",
            "tail_log": _tail_errors_log(cfg.buckets_dir),
        })
        if on_complete:
            on_complete(False)
        return

    # 2) 拉所有 bucket
    try:
        buckets = await cfg.fetch_buckets()
    except Exception as e:
        write_status(status_path, {
            **_empty_status(),
            "phase": "failed",
            "error": f"fetch buckets failed: {type(e).__name__}: {e}",
            "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "message": "迁移未启动：列出桶失败",
            "tail_log": _tail_errors_log(cfg.buckets_dir),
        })
        if on_complete:
            on_complete(False)
        return

    total = len(buckets)
    done_ids = _read_checkpoint(ckpt_path)  # 断点续传
    failed_items: list[dict[str, str]] = []
    failed_count = 0

    write_status(status_path, {
        **_empty_status(),
        "phase": "running",
        "total": total,
        "done": len(done_ids),
        "failed_count": 0,
        "current_id": "",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "target_backend": cfg.target_backend,
        "target_model": cfg.target_model,
        "target_dim": cfg.target_dim,
        "message": f"开始迁移 {total} 个 bucket（已完成 {len(done_ids)}）",
    })

    # 3) 分批跑
    pending = [(bid, content) for bid, content in buckets if bid not in done_ids]
    for i in range(0, len(pending), BATCH_SIZE):
        batch = pending[i:i + BATCH_SIZE]
        for bucket_id, content in batch:
            cur = read_status(status_path)
            cur["current_id"] = bucket_id
            write_status(status_path, cur)

            try:
                ok = await cfg.target_engine.generate_and_store(bucket_id, content)
                if not ok:
                    failed_count += 1
                    if len(failed_items) < MAX_FAILED_ITEMS:
                        failed_items.append({
                            "bucket_id": bucket_id,
                            "error": "generate_and_store returned False",
                        })
                else:
                    done_ids.add(bucket_id)
            except Exception as e:
                failed_count += 1
                if len(failed_items) < MAX_FAILED_ITEMS:
                    failed_items.append({
                        "bucket_id": bucket_id,
                        "error": f"{type(e).__name__}: {e}",
                    })

        # 每批写一次 checkpoint + status
        _write_checkpoint(ckpt_path, done_ids)
        cur = read_status(status_path)
        cur["done"] = len(done_ids)
        cur["failed_count"] = failed_count
        cur["failed_items"] = failed_items
        cur["message"] = f"已完成 {len(done_ids)} / {total}（失败 {failed_count}）"
        write_status(status_path, cur)

        # 限速
        if i + BATCH_SIZE < len(pending):
            await asyncio.sleep(BATCH_INTERVAL_SEC)

    # 4) 收尾：只要核心流程没崩，整体算 completed（失败条记在列表里）
    finished_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    final_phase = "completed"
    final_msg = f"迁移完成：{len(done_ids)} 成功 / {failed_count} 失败"
    tail = []
    if failed_count > 0:
        # 失败时附 log + 引导提示
        tail = _tail_errors_log(cfg.buckets_dir)

    cur = read_status(status_path)
    cur.update({
        "phase": final_phase,
        "current_id": "",
        "done": len(done_ids),
        "failed_count": failed_count,
        "failed_items": failed_items,
        "finished_at": finished_at,
        "message": final_msg,
        "tail_log": tail,
    })
    write_status(status_path, cur)

    # 成功后把 embeddings_meta 更新为目标后端的 model/dim，
    # 否则 db_meta 还是旧值（如 gemini/768），重启会误报 OB-W005 维度不一致。
    if failed_count == 0:
        try:
            cfg.target_engine._write_meta("model_name", cfg.target_model or "")
            cfg.target_engine._write_meta("vector_dim", str(cfg.target_dim or 0))
        except Exception as e:
            logger.warning(f"[migration] update meta failed: {e}")

    # 完成后清掉 checkpoint（下次切换从头开始）
    if failed_count == 0:
        try:
            if os.path.exists(ckpt_path):
                os.remove(ckpt_path)
        except OSError:
            pass

    if on_complete:
        try:
            on_complete(failed_count == 0)
        except Exception as e:
            logger.warning(f"[migration] on_complete callback failed: {e}")


def start_migration(
    cfg: MigrationConfig,
    loop: asyncio.AbstractEventLoop | None = None,
    on_complete: Callable[[bool], None] | None = None,
) -> asyncio.Task | None:
    """在指定 event loop 上启动后台迁移任务。

    同一时刻只允许一个迁移任务，重复调用返回 None。
    """
    global _migration_task
    if not _migration_lock.acquire(blocking=False):
        logger.info("[migration] another migration already in progress; skip")
        return None

    target_loop = loop or asyncio.get_event_loop()

    async def _wrap():
        try:
            await _run_migration(cfg, on_complete=on_complete)
        finally:
            _migration_lock.release()

    task = target_loop.create_task(_wrap())
    _migration_task = task
    return task


def is_running() -> bool:
    return _migration_lock.locked()


def reset_for_test() -> None:
    """测试用：强制释放锁。"""
    global _migration_task
    if _migration_lock.locked():
        try:
            _migration_lock.release()
        except RuntimeError:
            pass
    _migration_task = None


__all__ = [
    "MigrationConfig",
    "status_path_for",
    "checkpoint_path_for",
    "read_status",
    "write_status",
    "backup_db_once",
    "start_migration",
    "is_running",
    "reset_for_test",
    "attach_v3_runtime",
    "get_v3_runtime",
    "BATCH_SIZE",
    "BATCH_INTERVAL_SEC",
]
