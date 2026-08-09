"""
========================================
web/tunnel.py — Cloudflare Tunnel 管理（进程 + HTTP 路由）
========================================

把 dashboard 内置的 cloudflared 隧道管理从 server.py 拆出。
包含：隧道子进程的起停/状态、token 配置持久化（<buckets_dir>/.tunnel_config.json）、
以及 /api/tunnel/* 四个路由。

启动装配也会用到这里的 _load_tunnel_config / _start_tunnel / _stop_tunnel
（server.py 的 lifespan 在就绪后按配置自动起隧道、退出时停），故它们对外可见。

对外暴露：
- register(mcp)：注册 /api/tunnel/* 路由
- _load_tunnel_config / _start_tunnel / _stop_tunnel：供 server.py 启动/关停调用
========================================
"""

import os
import json as _json_lib
import shutil
import subprocess as _subprocess
import threading as _threading
from typing import Optional

from starlette.requests import Request
from starlette.responses import Response

from . import _shared as sh

try:
    from utils import parse_bool  # type: ignore
except ImportError:  # pragma: no cover
    from ..utils import parse_bool  # type: ignore

_tunnel_proc: Optional[_subprocess.Popen] = None
_tunnel_last_error: str = ""  # last captured stderr lines from cloudflared
_tunnel_config_lock = _threading.RLock()


def _get_tunnel_config_file() -> str:
    return os.path.join(sh.config["buckets_dir"], ".tunnel_config.json")


def _load_tunnel_config() -> dict:
    try:
        p = _get_tunnel_config_file()
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                return _json_lib.load(f)
    except Exception:
        pass
    return {}


def _save_tunnel_config(data: dict) -> None:
    path = _get_tunnel_config_file()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp.{os.getpid()}.{_threading.get_ident()}"
    payload = _json_lib.dumps(data, ensure_ascii=False)
    with _tunnel_config_lock:
        try:
            with open(tmp, "w", encoding="utf-8", newline="\n") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
            persisted = _load_tunnel_config()
            if persisted != data:
                raise OSError("tunnel config verification failed after write")
        finally:
            try:
                if os.path.exists(tmp):
                    os.unlink(tmp)
            except OSError:
                pass


def _tunnel_running() -> bool:
    global _tunnel_proc
    if _tunnel_proc is None:
        return False
    if _tunnel_proc.poll() is not None:
        _tunnel_proc = None
        return False
    return True


def _start_tunnel(token: str) -> tuple[bool, str]:
    global _tunnel_proc, _tunnel_last_error
    if _tunnel_running():
        return True, "already running"
    cf = shutil.which("cloudflared")
    if not cf:
        return False, ("cloudflared 未安装（镜像可能以 --build-arg INSTALL_CLOUDFLARED=0 构建）。"
                       "重新构建时去掉该参数，或手动安装 cloudflared 后再用隧道管理。")
    try:
        _tunnel_last_error = ""
        _tunnel_proc = _subprocess.Popen(
            [cf, "tunnel", "--no-autoupdate", "run", "--token", token],
            stdout=_subprocess.DEVNULL,
            stderr=_subprocess.PIPE,
        )
        # Capture stderr in background thread so we can surface errors
        def _read_stderr(proc):
            global _tunnel_last_error
            lines = []
            for line in iter(proc.stderr.readline, b""):
                text = line.decode("utf-8", errors="replace").strip()
                if text:
                    lines.append(text)
                    if len(lines) > 20:
                        lines.pop(0)
                    _tunnel_last_error = "\n".join(lines[-5:])
        _threading.Thread(target=_read_stderr, args=(_tunnel_proc,), daemon=True).start()
        return True, "started"
    except Exception as e:
        return False, str(e)


def _stop_tunnel() -> None:
    global _tunnel_proc
    if _tunnel_proc is not None:
        try:
            _tunnel_proc.terminate()
            _tunnel_proc.wait(timeout=5)
        except Exception:
            try:
                _tunnel_proc.kill()
            except Exception:
                pass
        _tunnel_proc = None


def register(mcp) -> None:
    """注册 /api/tunnel/* 路由到 FastMCP 实例。"""

    @mcp.custom_route("/api/tunnel/status", methods=["GET"])
    async def api_tunnel_status(request: Request) -> Response:
        from starlette.responses import JSONResponse
        err = sh._require_auth(request)
        if err:
            return err
        cfg = _load_tunnel_config()
        running = _tunnel_running()
        return JSONResponse({
            "running": running,
            "token_set": bool(cfg.get("token")),
            "auto_start": cfg.get("auto_start", False),
            "mcp_auth_required": parse_bool(
                sh.config.get("mcp_require_auth", True), default=True
            ),
            "last_error": _tunnel_last_error if not running else "",
        })

    @mcp.custom_route("/api/tunnel/config", methods=["POST"])
    async def api_tunnel_config(request: Request) -> Response:
        from starlette.responses import JSONResponse
        err = sh._require_auth(request)
        if err:
            return err
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid JSON"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"error": "JSON body must be an object"}, status_code=400)

        cfg = _load_tunnel_config()
        if "token" in body:
            token = body["token"]
            if not isinstance(token, str):
                return JSONResponse({"error": "token must be a string"}, status_code=400)
            token = token.strip()
            if token:
                cfg["token"] = token
        if "auto_start" in body:
            try:
                cfg["auto_start"] = parse_bool(body["auto_start"])
            except ValueError as e:
                return JSONResponse({"error": str(e)}, status_code=400)

        try:
            _save_tunnel_config(cfg)
            persisted = _load_tunnel_config()
        except Exception as exc:
            return JSONResponse({
                "error": f"tunnel config save failed: {exc}",
            }, status_code=500)
        return JSONResponse({
            "ok": True,
            "token_set": bool(persisted.get("token")),
            "auto_start": persisted.get("auto_start", False),
            "persisted": True,
        })

    @mcp.custom_route("/api/tunnel/start", methods=["POST"])
    async def api_tunnel_start(request: Request) -> Response:
        from starlette.responses import JSONResponse
        err = sh._require_auth(request)
        if err:
            return err
        cfg = _load_tunnel_config()
        token = cfg.get("token", "").strip()
        if not token:
            return JSONResponse({"error": "未配置 Token，请先保存 Token"}, status_code=400)
        ok, msg = _start_tunnel(token)
        if not ok:
            return JSONResponse({"error": msg}, status_code=500)
        return JSONResponse({"ok": True, "running": True})

    @mcp.custom_route("/api/tunnel/stop", methods=["POST"])
    async def api_tunnel_stop(request: Request) -> Response:
        from starlette.responses import JSONResponse
        err = sh._require_auth(request)
        if err:
            return err
        _stop_tunnel()
        return JSONResponse({"ok": True, "running": False})
