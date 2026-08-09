"""
========================================
web/embedding.py — 向量化后端摘要 / 迁移重算 / 本地 Ollama 模型管理
========================================
- /api/embedding/info、/api/embedding/migrate(+status)、/api/embedding/local/*
- 迁移成功后通过共享发布函数热替换所有 embedding 运行时引用，全局一致。
对外暴露：register(mcp)。
========================================
"""

import asyncio
import os
import httpx
import json as _json_lib
import yaml

from starlette.requests import Request
from starlette.responses import Response

from . import _shared as sh

logger = sh.logger

try:
    from errors import OBStartupError  # type: ignore
except ImportError:  # pragma: no cover
    from ..errors import OBStartupError  # type: ignore


def _persist_embedding_yaml(updates: dict) -> None:
    """把 embedding 配置写进 config.yaml（bind mount，重启/重建不丢）。

    迁移完成后必须调用：否则切到本地/云端只改了进程内 sh.config，重启后 config.yaml
    还是旧的 → 与 embeddings.db 里已重算的向量维度不一致 → OB-W005 / 检索失效。
    """
    try:
        from utils import config_file_path
        _cfg_path = config_file_path()
        _save: dict = {}
        if os.path.exists(_cfg_path):
            with open(_cfg_path, "r", encoding="utf-8") as _f:
                _save = yaml.safe_load(_f) or {}
        _sec = _save.setdefault("embedding", {})
        for k, v in updates.items():
            _sec[k] = v
        with open(_cfg_path, "w", encoding="utf-8") as _f:
            yaml.dump(_save, _f, allow_unicode=True, default_flow_style=False)
    except Exception as e:
        logger.error(f"[migration] persist embedding to config.yaml failed: {e}")


_DEFAULT_OLLAMA_BASE = "http://ombre-ollama:11434"
# 模型下载镜像前缀（registry）。空 = ollama 官方。国内慢/不通时可换。
_OLLAMA_MIRRORS = {
    "official": "",
    "modelscope": "modelscope.cn/",   # 形如 modelscope.cn/<ns>/bge-m3，需该源确有此模型
}

_ollama_pull_state: dict = {"running": False, "model": "", "percent": 0, "status": "idle", "error": ""}
_ollama_pull_task: "asyncio.Task | None" = None  # 持有引用防止被 GC

# --- backfill（只补缺失向量，区别于 migrate 全库重算）---
# 用途：v2.2 前建的桶（尤其 permanent）可能没有向量，
# embeddings.db 里没有它们的行 → breath 语义检索查不到。migrate 能修但会重算全库、
# 浪费 API 额度；backfill 只给「文件在、向量缺」的桶补一发，幂等、便宜。
_backfill_state: dict = {
    "running": False, "scanned": 0, "missing": 0, "done": 0,
    "failed": 0, "queued": 0, "status": "idle", "error": "",
}
_backfill_task: "asyncio.Task | None" = None  # 持有引用防止被 GC


def _ollama_base() -> str:
    """Ollama 管理 API 根地址（不带 /v1）。

    取值优先级：env OMBRE_OLLAMA_URL > 按宿主类型默认。
    Docker 里默认连同网络的 ombre-ollama 容器；裸机/原生默认本机 127.0.0.1
    （否则原生用户拉模型会去连一个不存在的容器名，静默失败）。
    """
    raw = (os.environ.get("OMBRE_OLLAMA_URL", "") or "").strip()
    if not raw:
        raw = _DEFAULT_OLLAMA_BASE if sh.in_docker() else "http://127.0.0.1:11434"
    return raw.rstrip("/").removesuffix("/v1").rstrip("/")


async def _ollama_pull_run(ollama_url: str, name: str) -> None:
    """后台流式拉模型，进度写入 _ollama_pull_state。"""
    global _ollama_pull_state
    _ollama_pull_state = {"running": True, "model": name, "percent": 0, "status": "starting", "error": ""}
    try:
        # trust_env=False：本地/容器 ollama 不走系统代理（否则 Clash/V2Ray 开着会 502）
        # Model pulls are long-running streams, so the read phase stays
        # unbounded while connect/write/pool waits remain finite.
        timeout = httpx.Timeout(connect=10.0, read=None, write=30.0, pool=10.0)
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as c:
            async with c.stream("POST", f"{ollama_url}/api/pull", json={"name": name, "stream": True}) as r:
                if r.status_code != 200:
                    raw = await r.aread()
                    _ollama_pull_state.update(running=False, status="error",
                                              error=f"HTTP {r.status_code}: {raw[:200].decode('utf-8','replace')}")
                    return
                async for line in r.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        ev = _json_lib.loads(line)
                    except Exception:
                        continue
                    if ev.get("error"):
                        _ollama_pull_state.update(running=False, status="error", error=str(ev["error"])[:200])
                        return
                    st = str(ev.get("status", ""))
                    _ollama_pull_state["status"] = st
                    total, completed = ev.get("total"), ev.get("completed")
                    if total and completed:
                        try:
                            _ollama_pull_state["percent"] = round(completed / total * 100, 1)
                        except Exception:
                            pass
                    if st == "success":
                        _ollama_pull_state.update(running=False, status="success", percent=100)
                        return
        _ollama_pull_state["running"] = False
    except Exception as e:
        _ollama_pull_state.update(running=False, status="error", error=str(e)[:200])


async def _backfill_run() -> None:
    """后台扫全库（含 archive），给缺向量的桶补 embedding，进度写 _backfill_state。

    每补一条更新计数；失败只累加 failed、不中断（rule.md §1.5 允许降级）。
    分批间小睡，照顾云端免费额度的速率限制。"""
    import asyncio as _aio
    global _backfill_state
    engine = sh.embedding_engine
    try:
        all_buckets = await sh.bucket_mgr.list_all(include_archive=True)
        _backfill_state["scanned"] = len(all_buckets)
        for key in ("orphaned", "cleaned", "cleanup_failed"):
            _backfill_state.setdefault(key, 0)

        # Reconcile both sides of the derived index.  Historically this action
        # only queued "bucket exists, vector missing" rows, while diagnostics
        # also reported the opposite drift (vector exists, bucket missing).
        # That made the Dashboard recommend backfill for orphan vectors and
        # then report "pending 0 / queued 0" forever.
        known_ids = {
            str(bucket.get("id") or "")
            for bucket in all_buckets
            if str(bucket.get("id") or "")
        }
        try:
            indexed_ids = set(engine.list_all_ids()) if engine else set()
        except Exception as exc:
            logger.warning("[backfill] could not list indexed ids: %s", exc)
            indexed_ids = set()
        orphan_ids = sorted(indexed_ids - known_ids)
        _backfill_state["orphaned"] = len(orphan_ids)
        for bucket_id in orphan_ids:
            try:
                engine.delete_embedding(bucket_id)
                _backfill_state["cleaned"] += 1
            except Exception as exc:
                _backfill_state["cleanup_failed"] += 1
                logger.warning("[backfill] orphan cleanup failed for %s: %s", bucket_id, exc)

        # Managed server runtimes have one durable writer for the derived
        # index. Reuse it so manual backfill, startup reconciliation, and
        # decay self-healing cannot race each other or bypass retry state.
        outbox = sh.embedding_outbox
        if outbox is not None and getattr(outbox, "running", False):
            queued = await outbox.reconcile(
                buckets=all_buckets,
                include_archive=True,
            )
            outbox.retry_now()
            queue_state = outbox.status()
            _backfill_state.update(
                missing=queue_state["pending"],
                failed=queue_state["retrying"],
                queued=queued,
                status="queued",
            )
            return

        # 先扫出缺向量的桶（空内容的跳过——没法向量化）
        missing: list[tuple[str, str]] = []
        for b in all_buckets:
            content = b.get("content", "")
            if not content or not content.strip():
                continue
            if await engine.get_embedding(b["id"]) is None:
                missing.append((b["id"], content))
        _backfill_state["missing"] = len(missing)
        _backfill_state["status"] = "embedding"

        for idx, (bid, content) in enumerate(missing):
            try:
                ok = await engine.generate_and_store(bid, content)
                if ok:
                    _backfill_state["done"] += 1
                else:
                    _backfill_state["failed"] += 1
            except Exception as e:
                _backfill_state["failed"] += 1
                logger.warning(f"[backfill] embed failed for {bid}: {e}")
            # 每 20 条小憩一下，避免打爆云端速率限制
            if (idx + 1) % 20 == 0:
                await _aio.sleep(2)

        _backfill_state["status"] = "done"
    except Exception as e:
        _backfill_state["status"] = "error"
        _backfill_state["error"] = str(e)[:200]
        logger.error(f"[backfill] run failed: {e}")
    finally:
        _backfill_state["running"] = False


def register(mcp) -> None:

    @mcp.custom_route("/api/embedding/info", methods=["GET"])
    async def api_embedding_info(request: Request) -> Response:
        """返回当前 embedding 后端的运行态摘要：backend / model / dim / enabled / db 状态。

        前端设置页用这个渲染「当前模型」面板。
        """
        from starlette.responses import JSONResponse
        err = sh._require_auth(request)
        if err:
            return err
        backend_obj = getattr(sh.embedding_engine, "_backend", None)
        info: dict[str, object] = {
            "ok": True,
            "backend": getattr(sh.embedding_engine, "backend", ""),
            "enabled": bool(getattr(sh.embedding_engine, "enabled", False)),
            "model": backend_obj.model_name() if backend_obj else "",
            "vector_dim": backend_obj.vector_dim() if backend_obj else 0,
            "db_path": getattr(sh.embedding_engine, "db_path", ""),
            "db_count": 0,
            "db_meta": {},
            "outbox": (
                sh.embedding_outbox.status()
                if sh.embedding_outbox is not None
                else None
            ),
        }
        # 主表行数
        try:
            import sqlite3
            if info["db_path"] and os.path.exists(str(info["db_path"])):
                conn = sqlite3.connect(str(info["db_path"]))
                try:
                    info["db_count"] = conn.execute(
                        "SELECT COUNT(*) FROM embeddings"
                    ).fetchone()[0]
                    rows = conn.execute(
                        "SELECT key, value FROM embeddings_meta"
                    ).fetchall()
                    info["db_meta"] = {k: v for k, v in rows}
                finally:
                    conn.close()
        except Exception as e:
            info["db_error"] = str(e)
        return JSONResponse(info)

    @mcp.custom_route("/api/embedding/migrate", methods=["POST"])
    async def api_embedding_migrate(request: Request) -> Response:
        """启动后台迁移任务：用目标后端重算所有 bucket 的 embedding。

        Body (JSON):
            target_backend: 'api' | 'gemini' | 'local' | 'ollama'（底层都映射到 backend=api）
            api_format:     可选 'gemini' | 'openai_compat' | 'ollama'
            api_key:        云端必填；本地（ollama）可空，引擎会补占位符
            base_url:       可选
            model:          可选

        成功启动返回 202，body 含 {ok, status_path}；
        已有任务在跑返回 409。
        """
        from starlette.responses import JSONResponse
        err = sh._require_auth(request)
        if err:
            return err

        try:
            body = await sh._read_json_object(request)
        except Exception:
            return JSONResponse({"ok": False, "error": "invalid JSON"}, status_code=400)

        migration_fields = (
            "target_backend", "api_format", "api_key", "base_url", "model"
        )
        if any(key in body and not isinstance(body[key], str) for key in migration_fields):
            return JSONResponse({"ok": False, "error": "migration fields must be strings"}, status_code=400)
        if any(len(body.get(key, "")) > 8192 for key in migration_fields):
            return JSONResponse({"ok": False, "error": "migration field is too large"}, status_code=400)
        target_backend_raw = str(body.get("target_backend", "")).strip().lower()
        # local/ollama 底层也是 openai_compat（backend=api），用 api_format 区分云端/本地
        target_backend = "api" if target_backend_raw in ("api", "gemini", "local", "ollama", "") else target_backend_raw
        if target_backend != "api":
            return JSONResponse({
                "ok": False,
                "error": f"target_backend 不支持：{target_backend_raw!r}",
            }, status_code=400)

        # 解析目标 api_format：显式传入优先；否则按 target_backend 推断
        req_api_format = str(body.get("api_format", "")).strip().lower()
        if not req_api_format:
            if target_backend_raw in ("local", "ollama"):
                req_api_format = "ollama"
            elif target_backend_raw == "gemini":
                req_api_format = "gemini"

        try:
            from migration_engine import (  # type: ignore
                MigrationConfig, start_migration, is_running,
                status_path_for as _mig_status_path_for,
            )
        except ImportError:
            from .migration_engine import (  # type: ignore
                MigrationConfig, start_migration, is_running,
                status_path_for as _mig_status_path_for,
            )

        if is_running():
            return JSONResponse({
                "ok": False,
                "error": "另一个迁移任务正在进行；请稍后再试或等其完成",
            }, status_code=409)

        # 构造目标引擎（不替换 global，跑完才替）
        target_cfg = _json_lib.loads(_json_lib.dumps(sh.config))  # 深拷贝
        target_emb_cfg = target_cfg.setdefault("embedding", {})
        target_emb_cfg["enabled"] = True
        target_emb_cfg["backend"] = target_backend
        if req_api_format:
            target_emb_cfg["api_format"] = req_api_format
        if body.get("api_key"):
            target_emb_cfg["api_key"] = str(body["api_key"]).strip()
        if body.get("base_url"):
            target_emb_cfg["base_url"] = str(body["base_url"]).strip()
        if body.get("model"):
            target_emb_cfg["model"] = str(body["model"]).strip()

        try:
            from embedding_engine import EmbeddingEngine  # type: ignore
        except ImportError:
            from ..embedding_engine import EmbeddingEngine  # type: ignore
        try:
            target_engine = EmbeddingEngine(target_cfg)
        except OBStartupError as oe:
            return JSONResponse({
                "ok": False,
                "error": f"目标引擎构造失败：{oe.error_code} {oe.detail}",
            }, status_code=400)
        except Exception as e:
            return JSONResponse({
                "ok": False,
                "error": f"目标引擎构造失败：{type(e).__name__}: {e}",
            }, status_code=400)

        target_backend_obj = getattr(target_engine, "_backend", None)

        # 预检（fail-fast）：先用目标引擎试嵌入一小段，确认后端真的可用，
        # 再决定要不要启动全库重算。否则切到本地但 bge-m3 没下载 / ollama 没起，
        # 会让 392 个桶逐个失败几分钟才发现 —— 体验极差。
        if target_backend_obj is None or not getattr(target_engine, "enabled", False):
            return JSONResponse({
                "ok": False,
                "error": "目标 embedding 引擎不可用（可能缺 key / 本地模型未就绪）。本地模式请先在「本地向量模型」面板下载 bge-m3。",
            }, status_code=400)
        try:
            _probe = await target_engine._generate_async("connectivity probe / 连接性探针")
        except Exception as e:
            _probe = []
            _probe_err = f"{type(e).__name__}: {e}"
        else:
            _probe_err = ""
        if not _probe:
            _hint = "本地模式：确认 ollama 容器在跑且 bge-m3 已下载（设置页「本地向量模型」面板）。" \
                if req_api_format in ("ollama", "local") else "云端模式：确认 API key / base_url / 网络可用。"
            return JSONResponse({
                "ok": False,
                "error": f"目标后端嵌入测试失败，已取消重算（不会动现有向量）。{_hint}" + (f"（{_probe_err}）" if _probe_err else ""),
            }, status_code=400)

        # 准备桶内容供给函数
        async def _fetch_buckets() -> list[tuple[str, str]]:
            all_buckets = await sh.bucket_mgr.list_all(include_archive=True)
            return [(b["id"], b["content"]) for b in all_buckets]

        buckets_dir = sh.config.get("buckets_dir", "buckets")
        db_path = getattr(sh.embedding_engine, "db_path", "")

        mig_cfg = MigrationConfig(
            buckets_dir=buckets_dir,
            db_path=db_path,
            target_backend=target_backend,
            target_model=target_backend_obj.model_name() if target_backend_obj else "",
            target_dim=target_backend_obj.vector_dim() if target_backend_obj else 0,
            target_engine=target_engine,
            fetch_buckets=_fetch_buckets,
        )

        outbox = sh.embedding_outbox
        outbox_was_running = bool(
            outbox is not None and getattr(outbox, "running", False)
        )

        def _restart_outbox() -> None:
            if not outbox_was_running or outbox is None:
                return
            try:
                import asyncio as _aio
                _aio.create_task(outbox.start(reconcile=True))
            except Exception as e:
                logger.error(f"[migration] embedding outbox restart failed: {e}")

        def _on_complete(success: bool) -> None:
            try:
                if not success:
                    logger.warning("[migration] task finished with failures; sh.embedding_engine NOT swapped")
                    return
                # 成功 → 把 global engine 切到目标
                sh.replace_embedding_engine(target_engine)
                # 持久化到 config（进程内 + config.yaml，重启/重建不丢）
                cfg_emb = sh.config.setdefault("embedding", {})
                cfg_emb["backend"] = target_backend
                cfg_emb["enabled"] = True
                _yaml_updates: dict = {"backend": target_backend, "enabled": True}
                # 持久化真实向量维度。迁移过程已生成过向量，target_backend_obj 的 _dim
                # 此刻是该模型的真实输出维度（如 bge-m3=1024）。若不落盘 dim，重启后
                # EmbeddingEngine 会按 openai_compat 默认 768 重新初始化 → 与 db(1024)
                # 对账误报 OB-W005、且重算十几遍/redeploy 都不消失（每次都在向量自校正
                # 之前对账）。这里把真实维度一并写进 config.yaml，重启即维度一致。
                _real_dim = target_backend_obj.vector_dim() if target_backend_obj else 0
                if _real_dim:
                    cfg_emb["dim"] = _real_dim
                    _yaml_updates["dim"] = _real_dim
                if req_api_format:
                    cfg_emb["api_format"] = req_api_format
                    _yaml_updates["api_format"] = req_api_format
                if body.get("api_key"):
                    cfg_emb["api_key"] = str(body["api_key"]).strip()
                    _yaml_updates["api_key"] = str(body["api_key"]).strip()
                if body.get("base_url"):
                    cfg_emb["base_url"] = str(body["base_url"]).strip()
                    _yaml_updates["base_url"] = str(body["base_url"]).strip()
                if body.get("model"):
                    cfg_emb["model"] = str(body["model"]).strip()
                    _yaml_updates["model"] = str(body["model"]).strip()
                _persist_embedding_yaml(_yaml_updates)
                logger.info(f"[migration] sh.embedding_engine swapped to backend={target_backend} format={req_api_format or '(unchanged)'}; persisted to config.yaml")
            except Exception as e:
                logger.error(f"[migration] post-swap failed: {e}")
            finally:
                _restart_outbox()

        # Migration rewrites the same SQLite index. Stop the normal queue
        # worker for the migration window, then restart it in the callback.
        if outbox_was_running:
            await outbox.stop()

        task = start_migration(mig_cfg, on_complete=_on_complete)
        if task is None:
            _restart_outbox()
            return JSONResponse({
                "ok": False,
                "error": "无法启动迁移任务（锁未获得）",
            }, status_code=409)

        return JSONResponse({
            "ok": True,
            "status_path": _mig_status_path_for(buckets_dir),
            "target_backend": target_backend,
        }, status_code=202)

    @mcp.custom_route("/api/embedding/migrate/status", methods=["GET"])
    async def api_embedding_migrate_status(request: Request) -> Response:
        """前端 3s 轮询：当前迁移任务状态。"""
        from starlette.responses import JSONResponse
        err = sh._require_auth(request)
        if err:
            return err
        try:
            from migration_engine import (  # type: ignore
                status_path_for as _mig_status_path_for,
                read_status as _mig_read_status,
                is_running,
            )
        except ImportError:
            from .migration_engine import (  # type: ignore
                status_path_for as _mig_status_path_for,
                read_status as _mig_read_status,
                is_running,
            )
        buckets_dir = sh.config.get("buckets_dir", "buckets")
        status = _mig_read_status(_mig_status_path_for(buckets_dir))
        return JSONResponse({"ok": True, "running": is_running(), "status": status})

    @mcp.custom_route("/api/embedding/backfill", methods=["POST"])
    async def api_embedding_backfill(request: Request) -> Response:
        """补齐缺失向量：只给 embeddings.db 里没有行的桶生成 embedding。

        与 /api/embedding/migrate 的区别：migrate 用（可能是新的）后端重算**全库**，
        backfill 只扫出「文件在、向量缺」的桶补一发，不动已有向量，便宜且幂等。
        典型场景：v2.2 前建的 permanent 桶让 breath 语义检索查不到。

        成功启动返回 202 + {ok, status_path}；已有 backfill/migrate 在跑返回 409。
        """
        from starlette.responses import JSONResponse
        global _backfill_task, _backfill_state
        err = sh._require_auth(request)
        if err:
            return err

        engine = sh.embedding_engine
        managed_outbox = bool(
            sh.embedding_outbox is not None
            and getattr(sh.embedding_outbox, "running", False)
        )
        if (not engine or not getattr(engine, "enabled", False)) and not managed_outbox:
            return JSONResponse({
                "ok": False,
                "error": "向量化未启用（缺 key / 本地模型未就绪），无法补齐。",
            }, status_code=400)

        # 与全库重算互斥：同时写 embeddings.db 会打架
        try:
            from migration_engine import is_running as _mig_running  # type: ignore
        except ImportError:
            try:
                from .migration_engine import is_running as _mig_running  # type: ignore
            except Exception:
                _mig_running = lambda: False  # noqa: E731
        if _mig_running():
            return JSONResponse({
                "ok": False,
                "error": "全库重算正在进行，请等它完成再补齐。",
            }, status_code=409)
        if _backfill_state.get("running"):
            return JSONResponse({
                "ok": False, "error": "已有补齐任务在进行中。",
            }, status_code=409)

        import asyncio as _aio
        _backfill_state = {
            "running": True, "scanned": 0, "missing": 0, "done": 0,
            "failed": 0, "queued": 0, "orphaned": 0, "cleaned": 0,
            "cleanup_failed": 0, "status": "scanning", "error": "",
        }
        _backfill_task = _aio.create_task(_backfill_run())
        return JSONResponse({
            "ok": True,
            "status_path": "/api/embedding/backfill/status",
        }, status_code=202)

    @mcp.custom_route("/api/embedding/backfill/status", methods=["GET"])
    async def api_embedding_backfill_status(request: Request) -> Response:
        """前端轮询：当前补齐任务进度。"""
        from starlette.responses import JSONResponse
        err = sh._require_auth(request)
        if err:
            return err
        outbox_state = (
            sh.embedding_outbox.status()
            if sh.embedding_outbox is not None
            else None
        )
        return JSONResponse({
            "ok": True,
            "backfill": _backfill_state,
            "outbox": outbox_state,
        })

    @mcp.custom_route("/api/embedding/local/status", methods=["GET"])
    async def api_embedding_local_status(request: Request) -> Response:
        """本地 ollama 是否可达 + 已有模型列表 + 目标模型是否就绪。"""
        from starlette.responses import JSONResponse
        err = sh._require_auth(request)
        if err:
            return err
        want = (request.query_params.get("model") or "bge-m3").strip()
        base = _ollama_base()
        out = {"ok": True, "ollama_url": base, "reachable": False, "models": [], "has_model": False, "mirrors": list(_OLLAMA_MIRRORS.keys())}
        try:
            async with httpx.AsyncClient(timeout=5.0, trust_env=False) as c:
                r = await c.get(f"{base}/api/tags")
                r.raise_for_status()
                names = [m.get("name", "") for m in r.json().get("models", [])]
                out["reachable"] = True
                out["models"] = names
                # ollama 模型名常带 :latest 后缀
                out["has_model"] = any(n == want or n.split(":")[0] == want for n in names)
        except Exception as e:
            out["error"] = str(e)[:160]
        out["pull"] = _ollama_pull_state
        return JSONResponse(out)

    @mcp.custom_route("/api/embedding/local/pull", methods=["POST"])
    async def api_embedding_local_pull(request: Request) -> Response:
        """触发后台拉模型。body: {model?: 'bge-m3', mirror?: 'official'|'modelscope'|<自定义前缀>}。"""
        from starlette.responses import JSONResponse
        err = sh._require_auth(request)
        if err:
            return err
        if _ollama_pull_state.get("running"):
            return JSONResponse({"ok": False, "error": "已有拉取任务在进行中"}, status_code=409)
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            return JSONResponse({"ok": False, "error": "JSON body must be an object"}, status_code=400)
        if any(
            key in body and not isinstance(body[key], str)
            for key in ("model", "mirror")
        ):
            return JSONResponse({"ok": False, "error": "model and mirror must be strings"}, status_code=400)
        model = (str(body.get("model") or "bge-m3")).strip()
        mirror_raw = (str(body.get("mirror") or "official")).strip()
        if len(model) > 512 or len(mirror_raw) > 2048:
            return JSONResponse({"ok": False, "error": "model or mirror is too large"}, status_code=400)
        prefix = _OLLAMA_MIRRORS.get(mirror_raw, mirror_raw if mirror_raw not in ("", "official") else "")
        name = f"{prefix}{model}" if prefix else model
        base = _ollama_base()
        # 可达性预检，避免后台任务静默失败
        try:
            async with httpx.AsyncClient(timeout=5.0, trust_env=False) as c:
                vr = await c.get(f"{base}/api/version")
                vr.raise_for_status()
        except Exception as e:
            return JSONResponse({"ok": False, "error": f"无法连接 ollama（{base}）：{str(e)[:120]}"}, status_code=502)
        import asyncio as _aio
        global _ollama_pull_task
        _ollama_pull_task = _aio.create_task(_ollama_pull_run(base, name))
        return JSONResponse({"ok": True, "started": True, "pulling": name})

    @mcp.custom_route("/api/embedding/local/pull/status", methods=["GET"])
    async def api_embedding_local_pull_status(request: Request) -> Response:
        from starlette.responses import JSONResponse
        err = sh._require_auth(request)
        if err:
            return err
        return JSONResponse({"ok": True, "pull": _ollama_pull_state})
