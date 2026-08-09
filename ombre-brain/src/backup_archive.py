"""Safe, verifiable local backup archives for Ombre Brain.

Markdown remains the source of truth.  The SQLite file is only a derived-index
snapshot, but exporting it consistently avoids a needless full reindex after a
restore.  A manifest detects incomplete/corrupted archives; it is an integrity
check, not a cryptographic signature of who created the archive.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import sqlite3
import tempfile
from typing import Any
import zipfile


MANIFEST_NAME = "backup_manifest.json"
MANIFEST_KIND = "ombre-brain-backup"
MANIFEST_SCHEMA_VERSION = 1

MIB = 1024 * 1024
MAX_ARCHIVE_BYTES = 512 * MIB
MAX_MEMBERS = 10_000
MAX_MEMBER_BYTES = 512 * MIB
MAX_TOTAL_UNCOMPRESSED_BYTES = 1024 * MIB
MAX_COMPRESSION_RATIO = 1000.0


class BackupArchiveError(ValueError):
    """The backup cannot be trusted or safely processed."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _normalize_member_path(raw_name: str) -> str:
    """Normalize legacy Windows ZIP names while rejecting traversal paths."""
    if not raw_name or "\x00" in raw_name:
        raise BackupArchiveError("备份包含空路径或 NUL 字符")
    name = raw_name.replace("\\", "/")
    if name.startswith("/"):
        raise BackupArchiveError(f"备份包含绝对路径: {raw_name}")
    parts = PurePosixPath(name).parts
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise BackupArchiveError(f"备份包含不安全路径: {raw_name}")
    if any(":" in part for part in parts):
        raise BackupArchiveError(f"备份包含盘符或非法路径: {raw_name}")
    return "/".join(parts)


def snapshot_sqlite(db_path: str) -> bytes:
    """Return a transactionally consistent SQLite snapshot."""
    if not db_path or not os.path.isfile(db_path):
        return b""
    fd, temp_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        source = sqlite3.connect(db_path, timeout=30)
        target = sqlite3.connect(temp_path)
        try:
            source.backup(target)
            result = target.execute("PRAGMA quick_check").fetchone()
            if not result or str(result[0]).lower() != "ok":
                raise BackupArchiveError("embeddings.db 快照完整性检查失败")
        finally:
            target.close()
            source.close()
        return Path(temp_path).read_bytes()
    finally:
        try:
            os.unlink(temp_path)
        except OSError:
            pass


def validate_sqlite_bytes(db_bytes: bytes) -> None:
    """Reject a corrupt or non-SQLite derived-index snapshot."""
    if not db_bytes:
        return
    fd, temp_path = tempfile.mkstemp(suffix=".db")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(db_bytes)
        connection = sqlite3.connect(temp_path)
        try:
            result = connection.execute("PRAGMA quick_check").fetchone()
            if not result or str(result[0]).lower() != "ok":
                raise BackupArchiveError("embeddings.db 已损坏")
        except sqlite3.DatabaseError as exc:
            raise BackupArchiveError(f"embeddings.db 无效: {exc}") from exc
        finally:
            connection.close()
    finally:
        try:
            os.unlink(temp_path)
        except OSError:
            pass


def _collect_markdown(buckets_dir: str) -> dict[str, bytes]:
    base = Path(buckets_dir).resolve()
    if not base.is_dir():
        raise BackupArchiveError(f"buckets_dir not found: {buckets_dir}")

    files: dict[str, bytes] = {}
    for path in sorted(base.rglob("*.md")):
        resolved = path.resolve()
        if not resolved.is_file() or not resolved.is_relative_to(base):
            raise BackupArchiveError(f"拒绝导出指向记忆目录外的文件: {path}")
        relative = resolved.relative_to(base).as_posix()
        arc_path = _normalize_member_path(f"buckets/{relative}")
        try:
            files[arc_path] = resolved.read_bytes()
        except OSError as exc:
            raise BackupArchiveError(f"无法读取记忆文件 {relative}: {exc}") from exc
    return files


def _build_manifest(files: dict[str, bytes], *, created_at: str, version: str) -> dict[str, Any]:
    entries = [
        {"path": path, "size": len(data), "sha256": _sha256(data)}
        for path, data in sorted(files.items())
    ]
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "kind": MANIFEST_KIND,
        "created_at": created_at,
        "version": version,
        "file_count": len(entries),
        "total_bytes": sum(item["size"] for item in entries),
        "files": entries,
    }


def build_export_archive(
    buckets_dir: str,
    embedding_db_path: str,
    export_meta: dict[str, Any],
) -> tuple[bytes, dict[str, Any]]:
    """Build a complete in-memory archive or fail without returning a partial one."""
    files = _collect_markdown(buckets_dir)
    db_bytes = snapshot_sqlite(embedding_db_path)
    if db_bytes:
        files["embeddings.db"] = db_bytes
    meta_bytes = json.dumps(
        export_meta, ensure_ascii=False, indent=2, default=str
    ).encode("utf-8")
    files["export_meta.json"] = meta_bytes

    manifest = _build_manifest(
        files,
        created_at=str(export_meta.get("exported_at") or ""),
        version=str(export_meta.get("version") or ""),
    )
    manifest_bytes = json.dumps(
        manifest, ensure_ascii=False, indent=2
    ).encode("utf-8")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        for path, data in sorted(files.items()):
            archive.writestr(path, data)
        archive.writestr(MANIFEST_NAME, manifest_bytes)
    payload = buffer.getvalue()
    if len(payload) > MAX_ARCHIVE_BYTES:
        raise BackupArchiveError("备份压缩后超过 512 MiB 上限")
    return payload, manifest


def _validate_infos(infos: list[zipfile.ZipInfo], archive_size: int) -> dict[str, zipfile.ZipInfo]:
    if archive_size > MAX_ARCHIVE_BYTES:
        raise BackupArchiveError("备份压缩包超过 512 MiB 上限")
    if len(infos) > MAX_MEMBERS:
        raise BackupArchiveError(f"备份文件项过多（上限 {MAX_MEMBERS}）")

    normalized: dict[str, zipfile.ZipInfo] = {}
    total = 0
    for info in infos:
        path = _normalize_member_path(info.filename.rstrip("/"))
        if info.is_dir():
            continue
        if path in normalized:
            raise BackupArchiveError(f"备份包含重复路径: {path}")
        if info.flag_bits & 0x1:
            raise BackupArchiveError(f"不支持加密 ZIP 成员: {path}")
        if info.file_size > MAX_MEMBER_BYTES:
            raise BackupArchiveError(f"备份成员过大: {path}")
        total += info.file_size
        if total > MAX_TOTAL_UNCOMPRESSED_BYTES:
            raise BackupArchiveError("备份解压后超过 1 GiB 上限")
        if info.file_size and not info.compress_size:
            raise BackupArchiveError(f"备份成员压缩信息异常: {path}")
        if info.file_size >= MIB:
            ratio = info.file_size / max(1, info.compress_size)
            if ratio > MAX_COMPRESSION_RATIO:
                raise BackupArchiveError(f"备份成员压缩率异常: {path}")
        normalized[path] = info
    return normalized


def _verify_manifest(manifest: Any, files: dict[str, bytes]) -> dict[str, Any]:
    if not isinstance(manifest, dict):
        raise BackupArchiveError("backup_manifest.json 必须是 JSON 对象")
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise BackupArchiveError("不支持的备份清单版本")
    if manifest.get("kind") != MANIFEST_KIND:
        raise BackupArchiveError("备份清单类型不正确")
    entries = manifest.get("files")
    if not isinstance(entries, list):
        raise BackupArchiveError("备份清单缺少 files")

    expected: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise BackupArchiveError("备份清单文件项格式错误")
        path = _normalize_member_path(str(entry.get("path") or ""))
        if path == MANIFEST_NAME or path in expected:
            raise BackupArchiveError(f"备份清单包含重复或递归路径: {path}")
        expected[path] = entry

    if set(expected) != set(files):
        missing = sorted(set(expected) - set(files))
        extra = sorted(set(files) - set(expected))
        raise BackupArchiveError(
            f"备份清单与实际文件不一致（missing={missing[:3]}, extra={extra[:3]}）"
        )
    if manifest.get("file_count") != len(files):
        raise BackupArchiveError("备份清单 file_count 不一致")
    total = sum(len(data) for data in files.values())
    if manifest.get("total_bytes") != total:
        raise BackupArchiveError("备份清单 total_bytes 不一致")

    for path, data in files.items():
        entry = expected[path]
        if entry.get("size") != len(data):
            raise BackupArchiveError(f"备份成员大小校验失败: {path}")
        if entry.get("sha256") != _sha256(data):
            raise BackupArchiveError(f"备份成员 SHA-256 校验失败: {path}")
    return manifest


def read_backup_archive(zip_bytes: bytes) -> dict[str, Any]:
    """Read a bounded archive and verify its manifest when present."""
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as archive:
            infos = _validate_infos(archive.infolist(), len(zip_bytes))
            files: dict[str, bytes] = {}
            for path, info in infos.items():
                try:
                    data = archive.read(info)
                except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
                    raise BackupArchiveError(f"无法读取备份成员 {path}: {exc}") from exc
                if len(data) != info.file_size:
                    raise BackupArchiveError(f"备份成员读取长度不一致: {path}")
                files[path] = data
    except zipfile.BadZipFile as exc:
        raise BackupArchiveError(f"无效的 ZIP 文件: {exc}") from exc

    manifest_bytes = files.pop(MANIFEST_NAME, None)
    if manifest_bytes is None:
        return {
            "files": files,
            "manifest": None,
            "integrity_verified": False,
            "integrity_warning": "旧版备份没有完整性清单；已执行 ZIP 安全检查，但无法确认文件是否齐全",
        }
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BackupArchiveError(f"backup_manifest.json 无法解析: {exc}") from exc
    verified = _verify_manifest(manifest, files)
    return {
        "files": files,
        "manifest": verified,
        "integrity_verified": True,
        "integrity_warning": "",
    }
