"""
========================================
web/import_api.py — 宿主机 vault 设置 / 历史对话导入 / 桶编辑 / 导出 / 记忆包迁移
========================================

- /api/host-vault：读写 docker-compose 挂载的宿主机记忆目录（写 .env）
- /api/import/*：上传历史对话、状态/暂停/模式/结果/复核
- /api/bucket/{id}/edit：编辑桶正文（带内容体积校验）
- /api/export：导出全部记忆 zip
- /api/migrate/*：记忆包 zip 上传 / 状态 / 应用

对外暴露：register(mcp)。
========================================
"""

import os
import time
import asyncio
from datetime import datetime as _dt

from starlette.requests import Request
from starlette.responses import Response

from . import _shared as sh

try:
    from utils import parse_bool  # type: ignore
except ImportError:  # pragma: no cover
    from ..utils import parse_bool  # type: ignore

try:
    from backup_archive import MAX_ARCHIVE_BYTES, BackupArchiveError, build_export_archive  # type: ignore
except ImportError:  # pragma: no cover
    from ..backup_archive import MAX_ARCHIVE_BYTES, BackupArchiveError, build_export_archive  # type: ignore

logger = sh.logger

try:
    from tools._common import (  # type: ignore
        check_content_size as _check_content_size,
        check_pinned_quota as _check_pinned_quota,
    )
except ImportError:  # pragma: no cover
    from ..tools._common import (  # type: ignore
        check_content_size as _check_content_size,
        check_pinned_quota as _check_pinned_quota,
    )

try:
    from import_memory import preview_import  # type: ignore
except ImportError:  # pragma: no cover
    from ..import_memory import preview_import  # type: ignore


_DEFAULT_MAX_IMPORT_UPLOAD_BYTES = 64 * 1024 * 1024


def _max_import_upload_bytes() -> int:
    limits = (getattr(sh, "config", {}) or {}).get("limits") or {}
    try:
        return max(1, int(limits.get("max_import_upload_bytes") or _DEFAULT_MAX_IMPORT_UPLOAD_BYTES))
    except (TypeError, ValueError):
        return _DEFAULT_MAX_IMPORT_UPLOAD_BYTES


async def _read_body_limited(request: Request, limit: int) -> bytes:
    raw_length = str((getattr(request, "headers", {}) or {}).get("content-length", "") or "").strip()
    if raw_length:
        try:
            length = int(raw_length)
        except ValueError:
            length = 0
        if length > limit:
            raise ValueError(f"Upload too large ({length} bytes > {limit} byte limit)")

    stream = getattr(request, "stream", None)
    if callable(stream):
        chunks: list[bytes] = []
        total = 0
        async for chunk in stream():
            total += len(chunk)
            if total > limit:
                raise ValueError(f"Upload too large ({total} bytes > {limit} byte limit)")
            chunks.append(chunk)
        return b"".join(chunks)

    body = await request.body()
    if len(body) > limit:
        raise ValueError(f"Upload too large ({len(body)} bytes > {limit} byte limit)")
    return body


async def _read_file_field_limited(file_field, limit: int) -> bytes:
    raw = await file_field.read(limit + 1)
    if len(raw) > limit:
        raise ValueError(f"Upload too large ({len(raw)} bytes > {limit} byte limit)")
    return raw


async def _read_import_upload_text(request: Request) -> tuple[str, str]:
    limit = _max_import_upload_bytes()
    content_type = request.headers.get("content-type", "")
    filename = ""
    if "multipart/form-data" in content_type:
        form = await request.form()
        file_field = form.get("file")
        if not file_field or isinstance(file_field, str):
            raise ValueError("No file field")
        raw_bytes = await _read_file_field_limited(file_field, limit)
        filename = getattr(file_field, "filename", "upload")
        return raw_bytes.decode("utf-8", errors="replace"), filename

    body = await _read_body_limited(request, limit)
    filename = request.query_params.get("filename", "upload")
    return body.decode("utf-8", errors="replace"), filename


def _import_llm_ready() -> bool:
    engine_dehydrator = getattr(getattr(sh, "import_engine", None), "dehydrator", None)
    if engine_dehydrator is not None:
        return bool(getattr(engine_dehydrator, "api_available", False))
    return bool(getattr(getattr(sh, "dehydrator", None), "api_available", False))


def register(mcp) -> None:

    @mcp.custom_route("/api/host-vault", methods=["GET"])
    async def api_host_vault_get(request: Request) -> Response:
        """Read the host-side vault path without pretending a container can change its mount."""
        from starlette.responses import JSONResponse
        err = sh._require_auth(request)
        if err:
            return err
        compose_managed = sh.in_docker()
        if compose_managed:
            # A container-local .env cannot affect the host-side volume source used
            # before this container starts. Only report the value Compose injected.
            value = os.environ.get("OMBRE_HOST_VAULT_DIR", "").strip()
            source = "env" if value else ""
            env_file = None
        else:
            value = sh._read_env_var("OMBRE_HOST_VAULT_DIR")
            source = "env" if os.environ.get("OMBRE_HOST_VAULT_DIR", "").strip() else ("file" if value else "")
            env_file = sh._project_env_path()
        return JSONResponse({
            "value": value,
            "source": source,
            "env_file": env_file,
            "compose_managed": compose_managed,
            "message": (
                "该挂载由宿主机 Compose 管理。请在 compose 文件旁的 .env 设置 "
                "OMBRE_HOST_VAULT_DIR，然后执行 docker compose up -d --force-recreate。"
                if compose_managed else ""
            ),
        })


    @mcp.custom_route("/api/host-vault", methods=["POST"])
    async def api_host_vault_set(request: Request) -> Response:
        """
        Persist OMBRE_HOST_VAULT_DIR for non-container deployments.
        Body: {"value": "/path/to/vault"}  (empty string clears the entry)

        Docker mounts are resolved by Compose before the container starts. Writing
        /app/src/.env from inside that container cannot change the host mount, so
        Docker callers receive an explicit host-managed response instead.
        """
        from starlette.responses import JSONResponse
        err = sh._require_auth(request)
        if err:
            return err
        if sh.in_docker():
            return JSONResponse({
                "error": (
                    "容器无法修改宿主机的 Compose 挂载。请在 compose 文件旁的 .env 设置 "
                    "OMBRE_HOST_VAULT_DIR，然后执行 docker compose up -d --force-recreate。"
                ),
                "compose_managed": True,
                "restart_required": True,
                "env_var": "OMBRE_HOST_VAULT_DIR",
            }, status_code=409)
        try:
            body = await sh._read_json_object(request)
        except Exception:
            return JSONResponse({"error": "invalid JSON"}, status_code=400)

        raw = body.get("value", "")
        if not isinstance(raw, str):
            return JSONResponse({"error": "value must be a string"}, status_code=400)
        value = raw.strip()

        # Reject characters that would break .env / shell parsing
        if "\n" in value or "\r" in value or '"' in value or "'" in value:
            return JSONResponse({"error": "value must not contain quotes or newlines"}, status_code=400)

        try:
            sh._write_env_var("OMBRE_HOST_VAULT_DIR", value)
        except Exception as e:
            return JSONResponse({"error": f"failed to write .env: {e}"}, status_code=500)

        return JSONResponse({
            "ok": True,
            "value": value,
            "env_file": sh._project_env_path(),
            "restart_required": True,
            "message": "已保存 OMBRE_HOST_VAULT_DIR；需要重启容器/服务后挂载才会生效。",
            "note": "已写入 .env；需在宿主机执行 `docker compose down && docker compose up -d` 让新挂载生效。",
        })


    # =============================================================
    # Import API — conversation history import
    # 导入 API — 对话历史导入
    # =============================================================

    @mcp.custom_route("/api/import/preflight", methods=["POST"])
    async def api_import_preflight(request: Request) -> Response:
        """Preview an import file without writing buckets or starting a job."""
        from starlette.responses import JSONResponse
        err = sh._require_auth(request)
        if err:
            return err

        try:
            raw_content, filename = await _read_import_upload_text(request)
        except Exception as e:
            return JSONResponse({"ok": False, "error": f"Failed to read upload: {e}"}, status_code=400)

        if not raw_content.strip():
            return JSONResponse({"ok": False, "error": "Empty file"}, status_code=400)

        human_label = str((sh.config or {}).get("human") or "用户")
        preview = preview_import(raw_content, filename=filename, human_label=human_label)
        import_running = bool(getattr(sh.import_engine, "is_running", False))
        llm_ready = _import_llm_ready()
        return JSONResponse({
            **preview,
            "filename": filename,
            "size_bytes": len(raw_content.encode("utf-8")),
            "import_running": import_running,
            "llm_ready": llm_ready,
            "can_start": bool(preview.get("ok")) and not import_running and llm_ready,
        })


    @mcp.custom_route("/api/import/upload", methods=["POST"])
    async def api_import_upload(request: Request) -> Response:
        """Upload a conversation file and start import."""
        from starlette.responses import JSONResponse
        err = sh._require_auth(request)
        if err:
            return err

        if sh.import_engine.is_running:
            return JSONResponse({"error": "Import already running"}, status_code=409)

        try:
            raw_content, filename = await _read_import_upload_text(request)

            if not raw_content.strip():
                return JSONResponse({"error": "Empty file"}, status_code=400)

            preserve_raw = request.query_params.get("preserve_raw", "").lower() in ("1", "true")
            resume = request.query_params.get("resume", "").lower() in ("1", "true")

        except Exception as e:
            return JSONResponse({"error": f"Failed to read upload: {e}"}, status_code=400)

        # Start import in background
        async def _run_import():
            try:
                await sh.import_engine.start(raw_content, filename, preserve_raw, resume)
            except Exception as e:
                logger.error(f"Import failed: {e}")

        asyncio.create_task(_run_import())

        return JSONResponse({
            "status": "started",
            "filename": filename,
            "size_bytes": len(raw_content.encode()),
        })


    @mcp.custom_route("/api/import/status", methods=["GET"])
    async def api_import_status(request: Request) -> Response:
        """Get current import progress."""
        from starlette.responses import JSONResponse
        err = sh._require_auth(request)
        if err:
            return err
        return JSONResponse(sh.import_engine.get_status())


    @mcp.custom_route("/api/import/pause", methods=["POST"])
    async def api_import_pause(request: Request) -> Response:
        """Pause the running import."""
        from starlette.responses import JSONResponse
        err = sh._require_auth(request)
        if err:
            return err
        if not sh.import_engine.is_running:
            return JSONResponse({"error": "No import running"}, status_code=400)
        sh.import_engine.pause()
        return JSONResponse({"status": "pause_requested"})


    @mcp.custom_route("/api/import/patterns", methods=["GET"])
    async def api_import_patterns(request: Request) -> Response:
        """Detect high-frequency patterns after import."""
        from starlette.responses import JSONResponse
        err = sh._require_auth(request)
        if err:
            return err
        try:
            patterns = await sh.import_engine.detect_patterns()
            return JSONResponse({"patterns": patterns})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)


    @mcp.custom_route("/api/import/results", methods=["GET"])
    async def api_import_results(request: Request) -> Response:
        """List recently imported/created buckets for review."""
        from starlette.responses import JSONResponse
        err = sh._require_auth(request)
        if err:
            return err
        try:
            limit = max(1, min(int(request.query_params.get("limit", "50")), 200))
        except (TypeError, ValueError, OverflowError):
            return JSONResponse({"error": "limit must be an integer in [1,200]"}, status_code=400)
        try:
            all_buckets = await sh.bucket_mgr.list_all(include_archive=False)
            # Sort by created time, newest first
            all_buckets.sort(key=lambda b: b["metadata"].get("created", ""), reverse=True)
            results = []
            for b in all_buckets[:limit]:
                results.append({
                    "id": b["id"],
                    "name": b["metadata"].get("name", ""),
                    "content": b["content"][:300],
                    "type": b["metadata"].get("type", ""),
                    "domain": b["metadata"].get("domain", []),
                    "tags": b["metadata"].get("tags", []),
                    "importance": b["metadata"].get("importance", 5),
                    "created": b["metadata"].get("created", ""),
                })
            return JSONResponse({"buckets": results, "total": len(all_buckets)})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)


    @mcp.custom_route("/api/import/review", methods=["POST"])
    async def api_import_review(request: Request) -> Response:
        """Apply review decisions: mark buckets as important/noise/pinned."""
        from starlette.responses import JSONResponse
        err = sh._require_auth(request)
        if err:
            return err
        try:
            body = await sh._read_json_object(request)
        except Exception:
            return JSONResponse({"error": "Invalid JSON"}, status_code=400)

        decisions = body.get("decisions", [])
        if not isinstance(decisions, list) or not decisions:
            return JSONResponse({"error": "No decisions provided"}, status_code=400)
        if len(decisions) > 1000:
            return JSONResponse({"error": "Too many review decisions (max 1000)"}, status_code=400)
        if any(not isinstance(decision, dict) for decision in decisions):
            return JSONResponse({"error": "Each decision must be an object"}, status_code=400)

        applied = 0
        errors = 0
        for d in decisions:
            bid = d.get("bucket_id", "")
            action = d.get("action", "")
            if (
                not isinstance(bid, str)
                or not isinstance(action, str)
                or len(bid) > 128
            ):
                errors += 1
                continue
            if not bid or not action:
                continue
            try:
                if action == "important":
                    await sh.bucket_mgr.update(bid, importance=9)
                elif action == "pin":
                    bucket = await sh.bucket_mgr.get(bid)
                    if not bucket:
                        errors += 1
                        continue
                    if not bucket.get("metadata", {}).get("pinned"):
                        quota_err = await _check_pinned_quota()
                        if quota_err:
                            logger.warning(f"Review pin rejected for {bid}: {quota_err}")
                            errors += 1
                            continue
                    ok = await sh.bucket_mgr.update(bid, pinned=True)
                    if ok is False:
                        errors += 1
                        continue
                elif action == "noise":
                    await sh.bucket_mgr.update(bid, resolved=True, importance=1)
                elif action == "delete":
                    await sh.bucket_mgr.delete(bid)
                applied += 1
            except Exception as e:
                logger.warning(f"Review action failed for {bid}: {e}")
                errors += 1

        return JSONResponse({"applied": applied, "errors": errors})


    # =============================================================
    # /api/bucket/{id}/edit  — iter 1.6 §6 trace 前端
    # 让 Dashboard 直接修改桶元数据：name / tags / importance / resolved /
    # pinned / digested / domain。content 也支持，会同步重建 embedding。
    # 内容大小受 §5 limits.max_bucket_bytes 约束；钉选量受 max_pinned 约束。
    # =============================================================
    @mcp.custom_route("/api/bucket/{bucket_id}/edit", methods=["PATCH", "POST"])
    async def api_bucket_edit(request: Request) -> Response:
        from starlette.responses import JSONResponse
        err = sh._require_auth(request)
        if err:
            return err
        bucket_id = request.path_params["bucket_id"]
        bucket = await sh.bucket_mgr.get(bucket_id)
        if not bucket:
            return JSONResponse({"error": "bucket not found"}, status_code=404)
        try:
            body = await sh._read_json_object(request)
        except Exception:
            return JSONResponse({"error": "invalid JSON"}, status_code=400)

        updates: dict = {}

        # --- 字符串型 ---
        if isinstance(body.get("name"), str):
            nm = body["name"].strip()[:120]
            if nm:
                updates["name"] = nm

        if isinstance(body.get("tags"), list):
            # 接受 ["a","b"]
            tags = [str(t).strip() for t in body["tags"] if str(t).strip()]
            updates["tags"] = tags
        elif isinstance(body.get("tags"), str):
            # 也接受 "a, b"
            tags = [t.strip() for t in body["tags"].split(",") if t.strip()]
            updates["tags"] = tags

        if isinstance(body.get("domain"), list):
            doms = [str(d).strip() for d in body["domain"] if str(d).strip()]
            updates["domain"] = doms
        elif isinstance(body.get("domain"), str) and body["domain"].strip():
            updates["domain"] = [d.strip() for d in body["domain"].split(",") if d.strip()]

        # --- 数值/布尔型 ---
        if "importance" in body:
            try:
                imp = int(body["importance"])
                if 1 <= imp <= 10:
                    updates["importance"] = imp
            except (TypeError, ValueError):
                pass

        for flag in ("resolved", "digested"):
            if flag in body:
                try:
                    updates[flag] = parse_bool(body[flag])
                except ValueError as e:
                    return JSONResponse({"error": str(e)}, status_code=400)

        # pinned 需要走配额检查
        if "pinned" in body:
            try:
                new_pinned = parse_bool(body["pinned"])
            except ValueError as e:
                return JSONResponse({"error": str(e)}, status_code=400)
            cur_pinned = bool(bucket["metadata"].get("pinned", False))
            if new_pinned and not cur_pinned:
                quota_err = await _check_pinned_quota()
                if quota_err:
                    return JSONResponse({"error": quota_err}, status_code=400)
                updates["pinned"] = True
                updates["importance"] = 10
                updates["type"] = "permanent"
            elif (not new_pinned) and cur_pinned:
                updates["pinned"] = False
                if bucket["metadata"].get("type") == "permanent":
                    updates["type"] = "dynamic"

        # content 替换 —— 走 §5 大小校验
        new_content = body.get("content")
        if isinstance(new_content, str) and new_content.strip() and new_content != bucket.get("content", ""):
            size_err = _check_content_size(new_content)
            if size_err:
                return JSONResponse({"error": size_err}, status_code=400)
            updates["content"] = new_content

        # type 字段直接改（不经 pinned 联动，调用方自己负责一致性）
        _valid_types = {"dynamic", "permanent", "feel", "plan", "letter", "i"}
        if isinstance(body.get("type"), str) and body["type"] in _valid_types:
            if body["type"] != bucket["metadata"].get("type"):
                updates["type"] = body["type"]

        if not updates:
            return JSONResponse({"error": "nothing to update"}, status_code=400)

        try:
            ok = await sh.bucket_mgr.update(bucket_id, **updates)
            if not ok:
                return JSONResponse({"error": "update failed"}, status_code=500)
            if "content" in updates:
                try:
                    sh.dehydrator.invalidate_cache(bucket["content"])
                except Exception:
                    pass
            return JSONResponse({"ok": True, "id": bucket_id, "updated": list(updates.keys())})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)


    # =============================================================
    # /api/export  — 完整记忆打包导出
    # 导出内容：所有 bucket markdown + SQLite 一致性快照 + meta + SHA-256 清单
    # 不导出 config（避免 api_key 等密钥泄露）
    # export_meta.json 中的 embedding 字段供导入端检查模型一致性。
    # =============================================================
    @mcp.custom_route("/api/export", methods=["GET"])
    async def api_export(request: Request) -> Response:
        from starlette.responses import StreamingResponse, JSONResponse
        err = sh._require_auth(request)
        if err:
            return err

        buckets_dir = sh.config.get("buckets_dir", "")
        if not buckets_dir or not os.path.isdir(buckets_dir):
            return JSONResponse({"error": f"buckets_dir not found: {buckets_dir}"}, status_code=500)

        try:
            emb_backend = getattr(sh.embedding_engine, "_backend", None)
            try:
                emb_dim = int(emb_backend.vector_dim()) if emb_backend else 0
            except Exception:
                emb_dim = 0
            meta: dict = {
                "exported_at": _dt.now().isoformat(timespec="seconds"),
                "version": sh.version,
                "embedding": {
                    "model": str(getattr(sh.embedding_engine, "model", "") or ""),
                    "dim": emb_dim,
                    "backend": str(getattr(sh.embedding_engine, "backend", "") or ""),
                },
            }
            try:
                meta["stats"] = await sh.bucket_mgr.get_stats()
            except Exception as exc:
                logger.warning("export: stats unavailable: %s", exc)

            emb_path = str(getattr(sh.embedding_engine, "db_path", "") or "")
            payload, manifest = await asyncio.to_thread(
                build_export_archive,
                buckets_dir,
                emb_path,
                meta,
            )
        except BackupArchiveError as e:
            return JSONResponse({"error": f"export failed: {e}"}, status_code=500)
        except Exception as e:
            logger.error("export failed", exc_info=True)
            return JSONResponse({"error": f"export failed: {e}"}, status_code=500)

        fname = f"ombre_export_{int(time.time())}.zip"
        return StreamingResponse(
            iter([payload]),
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{fname}"',
                "X-Ombre-Backup-Verified": "true",
                "X-Ombre-Backup-Files": str(manifest["file_count"]),
            },
        )


    # =============================================================
    # /api/migrate/* — 完整记忆包（zip）导入
    # 流程：POST /upload → GET /status（含冲突列表） → POST /apply（带决策）→ 轮询 GET /status
    # =============================================================

    @mcp.custom_route("/api/migrate/upload", methods=["POST"])
    async def api_migrate_upload(request: Request) -> Response:
        """上传 ombre_export_*.zip，解析内容并识别冲突，不实际写入。

        Body: multipart/form-data，字段名 'file'；或直接 POST zip 字节（Content-Type: application/zip）。
        成功返回解析状态（含冲突列表、embedding 模型匹配情况）。
        """
        from starlette.responses import JSONResponse
        err = sh._require_auth(request)
        if err:
            return err

        if sh.migrate_engine.is_busy:
            return JSONResponse({"error": "已有迁移任务正在进行，请等待完成后再上传"}, status_code=409)

        content_type = request.headers.get("content-type", "")
        try:
            if "multipart/form-data" in content_type:
                form = await request.form()
                file_field = form.get("file")
                if not file_field or isinstance(file_field, str):
                    return JSONResponse({"error": "缺少 file 字段"}, status_code=400)
                zip_bytes = await _read_file_field_limited(file_field, MAX_ARCHIVE_BYTES)
            else:
                zip_bytes = await _read_body_limited(request, MAX_ARCHIVE_BYTES)

            if not zip_bytes:
                return JSONResponse({"error": "文件为空"}, status_code=400)
        except Exception as e:
            return JSONResponse({"error": f"读取上传内容失败: {e}"}, status_code=400)

        result = await sh.migrate_engine.parse_zip(zip_bytes)
        if not result.get("ok"):
            return JSONResponse(result, status_code=422)
        return JSONResponse(result)


    @mcp.custom_route("/api/migrate/status", methods=["GET"])
    async def api_migrate_status(request: Request) -> Response:
        """查询当前迁移任务状态（解析结果、冲突列表、执行进度、重新向量化进度）。"""
        from starlette.responses import JSONResponse
        err = sh._require_auth(request)
        if err:
            return err
        return JSONResponse(sh.migrate_engine.get_status())


    @mcp.custom_route("/api/migrate/apply", methods=["POST"])
    async def api_migrate_apply(request: Request) -> Response:
        """执行导入，携带冲突决策。

        Body (JSON):
            decisions: {bucket_id: "skip" | "overwrite" | "keep_both"}

        无冲突的 bucket 自动导入，无需出现在 decisions 中。
        冲突但未在 decisions 中的 bucket 默认 skip（安全优先）。
        成功启动后台任务返回 202；任务完成前轮询 GET /api/migrate/status。
        """
        from starlette.responses import JSONResponse
        err = sh._require_auth(request)
        if err:
            return err

        if sh.migrate_engine.phase != "parsed":
            return JSONResponse(
                {"error": f"当前状态为 '{sh.migrate_engine.phase}'，apply 需要先完成 upload 解析（phase=parsed）"},
                status_code=409,
            )

        try:
            body = await sh._read_json_object(request)
        except Exception:
            return JSONResponse({"error": "invalid JSON"}, status_code=400)

        decisions: dict[str, str] = {}
        raw_decisions = body.get("decisions", {})
        if not isinstance(raw_decisions, dict):
            return JSONResponse({"error": "decisions must be an object"}, status_code=400)
        if len(raw_decisions) > 10_000:
            return JSONResponse({"error": "too many migration decisions"}, status_code=400)
        valid_opts = {"skip", "overwrite", "keep_both"}
        for bid, decision in raw_decisions.items():
            if isinstance(bid, str) and isinstance(decision, str) and decision in valid_opts:
                decisions[bid] = decision

        # 后台执行（apply 可能耗时较长，含重新向量化）
        async def _run_apply():
            try:
                await sh.migrate_engine.apply(decisions)
            except Exception as e:
                logger.error(f"[migrate] background apply error: {e}", exc_info=True)

        asyncio.create_task(_run_apply())

        return JSONResponse(
            {"ok": True, "message": "导入任务已启动，请轮询 GET /api/migrate/status 查看进度"},
            status_code=202,
        )
