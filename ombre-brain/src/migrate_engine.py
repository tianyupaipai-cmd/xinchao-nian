"""
========================================
migrate_engine.py — 完整记忆包导入引擎
========================================

把 /api/export 产生的 zip 包（buckets/*.md + embeddings.db + export_meta.json）
以增量 merge 方式写入当前系统。

关键行为：
- 解析 zip，识别 bucket 文件，读取 export_meta.json 中的 embedding 模型信息
- 对比导入包与当前系统的 embedding 模型，决定是否保留向量数据
- 检测 bucket ID 冲突，返回冲突列表等待她/他决策
- 冲突决策：skip（跳过）| overwrite（覆盖）| keep_both（保留两者，重分配 ID）
- embedding 模型一致 → 合并向量数据；不一致 → 仅导入 md 文件，完成后自动重新向量化

状态机：idle → parsed → applying → reindexing → done | error

不做什么：
- 不调用 LLM（不做内容解析/摘要/打标，只做文件迁移）
- 不修改 config
- 不做对话历史解析（那是 import_memory.py 的事）

对外暴露：MigrateEngine 类（被 server.py 实例化并注入路由）
========================================
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sqlite3
import tempfile
import uuid
from dataclasses import dataclass
from typing import Any, Optional

import frontmatter

try:
    from backup_archive import (  # type: ignore
        BackupArchiveError,
        read_backup_archive,
        validate_sqlite_bytes,
    )
    from utils import now_iso, safe_path, sanitize_name  # type: ignore
except ImportError:  # pragma: no cover
    from .backup_archive import BackupArchiveError, read_backup_archive, validate_sqlite_bytes  # type: ignore
    from .utils import now_iso, safe_path, sanitize_name  # type: ignore

logger = logging.getLogger("ombre_brain.migrate")

# ============================================================
# 状态常量
# ============================================================
PHASE_IDLE = "idle"
PHASE_PARSED = "parsed"
PHASE_APPLYING = "applying"
PHASE_REINDEXING = "reindexing"
PHASE_DONE = "done"
PHASE_ERROR = "error"

# bucket type → 存储子目录映射（与 bucket_manager.py 保持一致）
_TYPE_SUBDIR: dict[str, str] = {
    "permanent": "permanent",
    "dynamic": "dynamic",
    "archive": "archive",
    "archived": "archive",
    "feel": "feel",
    "plan": "plans",
    "letter": "letters",
}

# 默认子目录（unknown type 时）
_DEFAULT_SUBDIR = "dynamic"


# ============================================================
# 数据类
# ============================================================

@dataclass
class _ParsedBucket:
    """zip 内解析到的单个 bucket 文件。"""
    bucket_id: str
    arc_path: str        # zip 内路径，e.g. "buckets/dynamic/foo/name_id.md"
    md_bytes: bytes      # 原始文件字节
    name: str
    bucket_type: str
    domain: list[str]
    created: str


@dataclass
class ConflictInfo:
    """导入包内某 bucket_id 与当前系统冲突的描述。"""
    bucket_id: str
    import_name: str
    import_created: str
    current_name: str
    current_created: str


# ============================================================
# 辅助函数
# ============================================================

def _parse_md_meta(raw: bytes) -> tuple[dict, str]:
    """从 md 字节中解析 frontmatter 元数据 + 正文。失败返回空 dict + 空串。"""
    try:
        post = frontmatter.loads(raw.decode("utf-8", errors="replace"))
        return dict(post.metadata), post.content
    except Exception:
        return {}, ""


def _safe_str(val: Any, max_len: int = 512) -> str:
    """安全地将值转为字符串，并截断。"""
    return str(val)[:max_len] if val is not None else ""


# ============================================================
# MigrateEngine
# ============================================================

class MigrateEngine:
    """完整记忆包（zip）导入引擎。每个服务进程单例使用；同一时刻只允许一个任务。"""

    def __init__(self, config: dict, bucket_mgr: Any, embedding_engine: Any) -> None:
        self._config = config
        self._bucket_mgr = bucket_mgr
        self._embedding_engine = embedding_engine

        # ---- 状态 ----
        self._phase: str = PHASE_IDLE

        # ---- 解析阶段产物 ----
        self._parsed_buckets: list[_ParsedBucket] = []
        self._conflicts: list[ConflictInfo] = []
        self._import_model: str = ""
        self._import_model_dim: int = 0
        self._import_backend: str = ""
        self._has_embeddings: bool = False
        self._zip_db_bytes: Optional[bytes] = None
        self._integrity_verified: bool = False
        self._integrity_warning: str = ""
        self._backup_manifest: Optional[dict[str, Any]] = None

        # ---- 执行阶段计数 ----
        self._apply_total: int = 0
        self._apply_done: int = 0
        self._apply_imported: int = 0
        self._apply_skipped: int = 0
        self._apply_errors: list[str] = []

        # ---- 重新向量化阶段 ----
        self._reindex_total: int = 0
        self._reindex_done: int = 0
        self._reindex_errors: int = 0
        self._buckets_to_reindex: list[tuple[str, str]] = []  # (bucket_id, content)

        # ---- 错误信息 ----
        self._error_message: str = ""

    # ----------------------------------------------------------
    # 属性
    # ----------------------------------------------------------

    @property
    def phase(self) -> str:
        return self._phase

    @property
    def is_busy(self) -> bool:
        return self._phase in (PHASE_APPLYING, PHASE_REINDEXING)

    def _embedding_match(self) -> bool:
        """当前 embedding 模型是否与导入包一致。"""
        if not self._import_model:
            return False
        current_model = str(getattr(self._embedding_engine, "model", "") or "")
        same_model = (
            self._import_model.strip().lower().removeprefix("models/")
            == current_model.strip().lower().removeprefix("models/")
        )
        if not same_model:
            return False
        backend = getattr(self._embedding_engine, "_backend", None)
        try:
            current_dim = int(backend.vector_dim()) if backend else 0
        except Exception:
            current_dim = 0
        return not self._import_model_dim or not current_dim or self._import_model_dim == current_dim

    # ----------------------------------------------------------
    # 状态查询
    # ----------------------------------------------------------

    def get_status(self) -> dict:
        return {
            "phase": self._phase,
            "total_buckets": len(self._parsed_buckets),
            "conflicts_count": len(self._conflicts),
            "conflicts": [
                {
                    "bucket_id": c.bucket_id,
                    "import_name": c.import_name,
                    "import_created": c.import_created,
                    "current_name": c.current_name,
                    "current_created": c.current_created,
                }
                for c in self._conflicts
            ],
            "import_model": self._import_model,
            "import_backend": self._import_backend,
            "current_model": getattr(self._embedding_engine, "model", ""),
            "embedding_match": self._embedding_match(),
            "has_embeddings": self._has_embeddings,
            "integrity_verified": self._integrity_verified,
            "integrity_warning": self._integrity_warning,
            "backup_manifest": {
                "schema_version": self._backup_manifest.get("schema_version"),
                "created_at": self._backup_manifest.get("created_at", ""),
                "version": self._backup_manifest.get("version", ""),
                "file_count": self._backup_manifest.get("file_count", 0),
                "total_bytes": self._backup_manifest.get("total_bytes", 0),
            } if self._backup_manifest else None,
            "apply_progress": {
                "done": self._apply_done,
                "total": self._apply_total,
            },
            "reindex_progress": {
                "done": self._reindex_done,
                "total": self._reindex_total,
                "errors": self._reindex_errors,
            },
            "apply_errors": self._apply_errors[-20:],
            "result": {
                "imported": self._apply_imported,
                "skipped": self._apply_skipped,
            },
            "error": self._error_message,
        }

    # ----------------------------------------------------------
    # 第一步：解析 zip
    # ----------------------------------------------------------

    async def parse_zip(self, zip_bytes: bytes) -> dict:
        """解析 zip 字节，识别 buckets 文件和 embedding 信息，检测 ID 冲突。

        解析成功后 phase → 'parsed'，并返回包含冲突列表的状态字典。
        """
        if self.is_busy:
            return {"ok": False, "error": f"当前状态为 {self._phase}，请等待任务完成后再上传"}

        # 重置所有状态
        self._phase = PHASE_IDLE
        self._parsed_buckets = []
        self._conflicts = []
        self._import_model = ""
        self._import_model_dim = 0
        self._import_backend = ""
        self._has_embeddings = False
        self._zip_db_bytes = None
        self._integrity_verified = False
        self._integrity_warning = ""
        self._backup_manifest = None
        self._apply_errors = []
        self._apply_imported = 0
        self._apply_skipped = 0
        self._apply_total = 0
        self._apply_done = 0
        self._buckets_to_reindex = []
        self._reindex_total = 0
        self._reindex_done = 0
        self._reindex_errors = 0
        self._error_message = ""

        # ---- 在线程中解析 zip（避免阻塞事件循环）----
        try:
            parsed = await asyncio.to_thread(self._parse_zip_sync, zip_bytes)
        except Exception as e:
            self._phase = PHASE_ERROR
            self._error_message = f"zip 解析失败: {e}"
            logger.error(f"[migrate] parse_zip error: {e}", exc_info=True)
            return {"ok": False, "error": self._error_message}

        self._parsed_buckets = parsed["buckets"]
        self._import_model = parsed["import_model"]
        self._import_model_dim = parsed["import_model_dim"]
        self._import_backend = parsed["import_backend"]
        self._has_embeddings = parsed["has_embeddings"]
        self._zip_db_bytes = parsed.get("db_bytes")
        self._integrity_verified = bool(parsed.get("integrity_verified"))
        self._integrity_warning = str(parsed.get("integrity_warning") or "")
        self._backup_manifest = parsed.get("manifest")

        if not self._parsed_buckets:
            self._phase = PHASE_ERROR
            self._error_message = "zip 内未找到任何 bucket markdown 文件（期望路径前缀：buckets/）"
            return {"ok": False, "error": self._error_message}

        # ---- 识别冲突（需要异步查当前桶） ----
        await self._identify_conflicts()

        self._phase = PHASE_PARSED
        return {
            "ok": True,
            **self.get_status(),
        }

    def _parse_zip_sync(self, zip_bytes: bytes) -> dict:
        """同步解析 zip（在 to_thread 中执行）。"""
        buckets: list[_ParsedBucket] = []
        import_model = ""
        import_model_dim = 0
        import_backend = ""
        has_embeddings = False
        db_bytes: Optional[bytes] = None

        package = read_backup_archive(zip_bytes)
        files: dict[str, bytes] = package["files"]
        names = set(files)

        # 1) 读取 export_meta.json → 获取 embedding 模型信息
        if "export_meta.json" in names:
            try:
                meta = json.loads(files["export_meta.json"].decode("utf-8"))
                emb_info = meta.get("embedding", {})
                import_model = str(emb_info.get("model", "") or "")
                import_model_dim = int(emb_info.get("dim") or 0)
                import_backend = str(emb_info.get("backend", "") or "")
            except Exception as e:
                logger.warning(f"[migrate] export_meta.json 解析失败，将跳过向量恢复: {e}")

        # 2) 检查是否包含 embeddings.db；损坏快照不能伪装成可恢复索引。
        if "embeddings.db" in names:
            db_bytes = files["embeddings.db"]
            validate_sqlite_bytes(db_bytes)
            has_embeddings = bool(db_bytes)

        # 3) 遍历 bucket markdown 文件。任何损坏项都会让整个恢复预检失败，
        # 避免界面显示“成功”但实际静默漏掉记忆。
        seen_ids: set[str] = set()
        for arc_path in sorted(names):
            if not arc_path.startswith("buckets/") or not arc_path.endswith(".md"):
                continue
            try:
                raw = files[arc_path]
                post = frontmatter.loads(raw.decode("utf-8"))
                meta = dict(post.metadata)

                bucket_id = str(meta.get("id") or meta.get("bucket_id") or "")
                if not bucket_id:
                    stem = os.path.splitext(os.path.basename(arc_path))[0]
                    parts = stem.rsplit("_", 1)
                    bucket_id = parts[-1] if len(parts) > 1 else stem

                if (
                    not bucket_id
                    or len(bucket_id) > 200
                    or any(ord(char) < 32 for char in bucket_id)
                    or "/" in bucket_id
                    or "\\" in bucket_id
                ):
                    raise BackupArchiveError(f"{arc_path} 的 bucket_id 不安全或为空")
                if bucket_id in seen_ids:
                    raise BackupArchiveError(f"备份中存在重复 bucket_id: {bucket_id}")
                seen_ids.add(bucket_id)

                domain = meta.get("domain") or []
                if isinstance(domain, str):
                    domain = [domain]
                elif not isinstance(domain, list):
                    domain = []
                buckets.append(_ParsedBucket(
                    bucket_id=bucket_id,
                    arc_path=arc_path,
                    md_bytes=raw,
                    name=_safe_str(meta.get("name", bucket_id), 200),
                    bucket_type=_safe_str(meta.get("type", "dynamic"), 32),
                    domain=[_safe_str(item, 100) for item in domain],
                    created=_safe_str(meta.get("created", ""), 32),
                ))
            except BackupArchiveError:
                raise
            except Exception as e:
                raise BackupArchiveError(f"bucket markdown 无法解析: {arc_path}: {e}") from e

        return {
            "buckets": buckets,
            "import_model": import_model,
            "import_model_dim": import_model_dim,
            "import_backend": import_backend,
            "has_embeddings": has_embeddings,
            "db_bytes": db_bytes,
            "integrity_verified": package["integrity_verified"],
            "integrity_warning": package["integrity_warning"],
            "manifest": package["manifest"],
        }

    async def _identify_conflicts(self) -> None:
        """遍历解析到的 bucket，查询当前系统，找出 ID 冲突。"""
        conflicts: list[ConflictInfo] = []
        for pb in self._parsed_buckets:
            existing = await self._bucket_mgr.get(pb.bucket_id)
            if existing is not None:
                emeta = existing.get("metadata", {})
                conflicts.append(ConflictInfo(
                    bucket_id=pb.bucket_id,
                    import_name=pb.name,
                    import_created=pb.created,
                    current_name=_safe_str(emeta.get("name", pb.bucket_id), 200),
                    current_created=_safe_str(emeta.get("created", ""), 32),
                ))
        self._conflicts = conflicts

    # ----------------------------------------------------------
    # 第二步：执行导入（带冲突决策）
    # ----------------------------------------------------------

    async def apply(self, decisions: dict[str, str]) -> None:
        """执行导入。

        decisions: {bucket_id: "skip" | "overwrite" | "keep_both"}
        冲突但未出现在 decisions 中的 bucket → 默认 skip（安全优先）。
        无冲突的 bucket 直接导入，无需决策。
        """
        if self._phase != PHASE_PARSED:
            raise RuntimeError(f"当前状态为 {self._phase}，apply 需要先完成 parse_zip")

        self._phase = PHASE_APPLYING
        self._apply_total = len(self._parsed_buckets)
        self._apply_done = 0
        self._apply_imported = 0
        self._apply_skipped = 0
        self._apply_errors = []
        self._buckets_to_reindex = []

        conflict_ids = {c.bucket_id for c in self._conflicts}
        embedding_matches = self._embedding_match()
        buckets_dir = self._config.get("buckets_dir", "buckets")
        imported_id_map: dict[str, str] = {}
        imported_contents: dict[str, str] = {}

        try:
            for pb in self._parsed_buckets:
                try:
                    is_conflict = pb.bucket_id in conflict_ids
                    decision = decisions.get(pb.bucket_id, "skip") if is_conflict else "import"

                    if is_conflict and decision == "skip":
                        self._apply_skipped += 1
                        self._apply_done += 1
                        continue

                    if is_conflict and decision == "overwrite":
                        # OB 不做物理抹除：旧桶先软删除归档，再换一个历史 ID，
                        # 把原 ID 留给导入版本。否则 active/archive 会出现重复 ID。
                        await self._bucket_mgr.delete(pb.bucket_id)
                        await asyncio.to_thread(
                            self._rekey_archived_conflict, pb.bucket_id
                        )
                        target_id = pb.bucket_id
                    elif is_conflict and decision == "keep_both":
                        # 分配新 ID，两个桶共存
                        target_id = str(uuid.uuid4())
                    else:
                        # 无冲突，直接用原 ID
                        target_id = pb.bucket_id

                    # 写入 markdown 文件
                    content = await asyncio.to_thread(
                        self._write_bucket_file, pb, target_id, buckets_dir
                    )
                    self._apply_imported += 1
                    imported_id_map[pb.bucket_id] = target_id
                    imported_contents[target_id] = content

                except Exception as e:
                    err_msg = f"[{pb.bucket_id}] {pb.name[:60]}: {e}"
                    logger.error(f"[migrate] apply error: {err_msg}", exc_info=True)
                    self._apply_errors.append(err_msg)
                    self._apply_skipped += 1

                self._apply_done += 1

            # ---- 向量数据处理 ----
            merged_ids: set[str] = set()
            if embedding_matches and self._has_embeddings and self._zip_db_bytes:
                # 模型与维度一致时复用快照向量。keep_both 会把源 ID 映射到新 ID。
                try:
                    merged_ids = await asyncio.to_thread(
                        self._merge_embeddings,
                        self._zip_db_bytes,
                        imported_id_map,
                    )
                except Exception as e:
                    message = f"向量快照合并失败，已转入后台重建: {e}"
                    logger.warning("[migrate] %s", message)
                    self._apply_errors.append(message)

            self._buckets_to_reindex = [
                (target_id, content)
                for target_id, content in imported_contents.items()
                if target_id not in merged_ids and content.strip()
            ]
            await self._schedule_reindex()

            invalidate = getattr(self._bucket_mgr, "_invalidate_bm25", None)
            if callable(invalidate):
                invalidate()
            self._phase = PHASE_DONE

        except Exception as e:
            self._phase = PHASE_ERROR
            self._error_message = str(e)
            logger.error(f"[migrate] apply failed: {e}", exc_info=True)

    def _write_bucket_file(
        self, pb: _ParsedBucket, target_id: str, buckets_dir: str
    ) -> str:
        """（在线程中执行）写入 bucket markdown 文件，返回正文内容。"""
        meta, content = _parse_md_meta(pb.md_bytes)

        # 始终写显式 ID；恢复不依赖文件名猜测。
        meta["id"] = target_id

        # 确定目标目录（按类型 + domain）
        btype = str(meta.get("type") or pb.bucket_type or "dynamic")
        subdir = _TYPE_SUBDIR.get(btype, _DEFAULT_SUBDIR)

        # 获取主 domain（与 bucket_manager 保持一致）
        domain = meta.get("domain") or pb.domain or []
        if btype == "feel":
            primary_domain = "沉淀物"
        elif btype == "plan":
            primary_domain = str(meta.get("status", "active") or "active")
        elif btype == "letter":
            primary_domain = "history"
        elif isinstance(domain, list) and domain:
            primary_domain = str(domain[0])
        elif isinstance(domain, str) and domain:
            primary_domain = str(domain)
        else:
            primary_domain = "general"

        primary_domain = sanitize_name(primary_domain)
        target_dir = str(safe_path(buckets_dir, os.path.join(subdir, primary_domain)))
        os.makedirs(target_dir, exist_ok=True)

        safe_id = re.sub(r"[^\w.-]", "_", target_id, flags=re.UNICODE)[:200]
        if not safe_id:
            raise BackupArchiveError("恢复目标 ID 无法生成安全文件名")
        safe_name = sanitize_name(str(meta.get("name") or pb.name or target_id))[:40]
        target_path = str(safe_path(target_dir, f"{safe_name}_{safe_id}.md"))

        # 重新序列化 frontmatter + 正文
        post = frontmatter.Post(content, **meta)
        rendered = frontmatter.dumps(post)
        temp_path = f"{target_path}.{uuid.uuid4().hex}.tmp"
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                f.write(rendered)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, target_path)
        finally:
            try:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
            except OSError:
                pass

        logger.debug(f"[migrate] wrote {target_path} (id={target_id})")
        return content

    def _rekey_archived_conflict(self, bucket_id: str) -> str:
        """Give the preserved pre-overwrite archive a unique historical ID."""
        finder = getattr(self._bucket_mgr, "_find_bucket_file", None)
        file_path = finder(bucket_id) if callable(finder) else None
        if not file_path:
            raise BackupArchiveError(f"覆盖前的旧桶归档后无法定位: {bucket_id}")
        post = frontmatter.load(file_path)
        new_id = f"{bucket_id[:160]}-superseded-{uuid.uuid4().hex[:12]}"
        post["id"] = new_id
        post["superseded_by"] = bucket_id
        safe_name = sanitize_name(str(post.get("name") or "memory"))[:40]
        target_path = str(safe_path(
            os.path.dirname(file_path),
            f"{safe_name}_{new_id}.md",
        ))
        temp_path = f"{target_path}.{uuid.uuid4().hex}.tmp"
        try:
            with open(temp_path, "w", encoding="utf-8") as handle:
                handle.write(frontmatter.dumps(post))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, target_path)
            if os.path.abspath(target_path) != os.path.abspath(file_path):
                os.unlink(file_path)
        finally:
            try:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
            except OSError:
                pass
        return new_id

    def _merge_embeddings(self, db_bytes: bytes, id_map: dict[str, str]) -> set[str]:
        """（在线程中执行）把 zip 内 embeddings.db 的向量合并进当前 db。

        兼容当前 bucket_id/embedding schema 和早期 id/vector schema。
        返回成功恢复向量的目标 bucket ID 集合。
        """
        current_db = getattr(self._embedding_engine, "db_path", "")
        if not current_db or not os.path.isfile(current_db):
            logger.warning("[migrate] 当前 embeddings.db 路径无效，跳过向量合并")
            return set()

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
            tf.write(db_bytes)
            tmp_path = tf.name

        try:
            src = sqlite3.connect(tmp_path, timeout=30)
            dst = sqlite3.connect(current_db, timeout=30)
            try:
                # 检查表结构是否存在
                tables = {row[0] for row in src.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()}
                if "embeddings" not in tables:
                    logger.warning("[migrate] 导入包 embeddings.db 缺少 embeddings 表，跳过")
                    return set()

                if not id_map:
                    return set()

                columns = {
                    str(row[1]) for row in src.execute("PRAGMA table_info(embeddings)").fetchall()
                }
                placeholders = ",".join("?" * len(id_map))
                source_ids = tuple(id_map)
                if {"bucket_id", "embedding"}.issubset(columns):
                    updated_expr = "updated_at" if "updated_at" in columns else "''"
                    hash_expr = "content_hash" if "content_hash" in columns else "''"
                    rows = src.execute(
                        f"SELECT bucket_id, embedding, {updated_expr}, {hash_expr} "  # nosec B608
                        f"FROM embeddings WHERE bucket_id IN ({placeholders})",
                        source_ids,
                    ).fetchall()
                elif {"id", "vector"}.issubset(columns):
                    rows = [
                        (source_id, vector, "", "")
                        for source_id, vector in src.execute(
                            f"SELECT id, vector FROM embeddings WHERE id IN ({placeholders})",  # nosec B608
                            source_ids,
                        ).fetchall()
                    ]
                else:
                    raise BackupArchiveError("embeddings 表结构无法识别")

                merged: set[str] = set()
                if rows:
                    normalized_rows = []
                    for source_id, embedding, updated_at, content_hash in rows:
                        target_id = id_map.get(str(source_id))
                        if not target_id:
                            continue
                        normalized_rows.append((
                            target_id,
                            embedding,
                            str(updated_at or now_iso()),
                            str(content_hash or ""),
                        ))
                        merged.add(target_id)
                    dst.executemany(
                        """INSERT OR REPLACE INTO embeddings
                           (bucket_id, embedding, updated_at, content_hash)
                           VALUES (?, ?, ?, ?)""",
                        normalized_rows,
                    )
                    dst.commit()
                    logger.info(f"[migrate] 合并了 {len(merged)} 条 embedding 向量")
                return merged
            finally:
                src.close()
                dst.close()
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    async def _schedule_reindex(self) -> None:
        """Durably queue missing derived indexes; only legacy runtimes index inline."""
        self._reindex_total = len(self._buckets_to_reindex)
        self._reindex_done = 0
        self._reindex_errors = 0
        if not self._buckets_to_reindex:
            return

        outbox = getattr(self._bucket_mgr, "embedding_outbox", None)
        if outbox is not None and callable(getattr(outbox, "enqueue", None)):
            for bucket_id, content in self._buckets_to_reindex:
                try:
                    outbox.enqueue(bucket_id, content)
                except Exception as exc:
                    self._reindex_errors += 1
                    self._apply_errors.append(f"[{bucket_id}] 无法加入向量队列: {exc}")
                self._reindex_done += 1
            return

        self._phase = PHASE_REINDEXING
        await self._reindex_all()

    async def _reindex_all(self) -> None:
        """对 embedding 不匹配时导入的 bucket 重新生成向量。"""
        emb = self._embedding_engine
        if not getattr(emb, "enabled", False):
            logger.warning("[migrate] embedding engine 未启用，跳过重新向量化")
            self._phase = PHASE_DONE
            return

        for bucket_id, content in self._buckets_to_reindex:
            if not content.strip():
                self._reindex_done += 1
                continue
            try:
                await emb.generate_and_store(bucket_id, content)
            except Exception as e:
                logger.warning(f"[migrate] reindex {bucket_id[:12]}: {e}")
                self._reindex_errors += 1
            self._reindex_done += 1

        logger.info(
            f"[migrate] 重新向量化完成: "
            f"{self._reindex_done - self._reindex_errors} 成功, "
            f"{self._reindex_errors} 失败"
        )
        self._phase = PHASE_DONE
