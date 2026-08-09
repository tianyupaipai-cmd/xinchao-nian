"""
Read-only v2.4.0 decision debug routes.

These endpoints expose Decision Ledger and Replay Debugger state to the
Dashboard without executing legacy handlers or mutating storage.
"""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import Response

from . import _shared as sh

_MAX_LIMIT = 100
_DEFAULT_LIMIT = 20


def register(mcp) -> None:

    @mcp.custom_route("/api/v3/debug/decisions", methods=["GET"])
    async def api_v3_debug_decisions(request: Request) -> Response:
        from starlette.responses import JSONResponse

        err = sh._require_auth(request)
        if err:
            return err
        runtime = getattr(sh, "v3_runtime", None)
        if runtime is None or not hasattr(runtime, "debug_decisions"):
            return JSONResponse({"ok": False, "available": False, "records": [], "count": 0, "problems": []})
        limit = _limit(request.query_params.get("limit", str(_DEFAULT_LIMIT)))
        module = str(request.query_params.get("module", "") or "")
        operation = str(request.query_params.get("operation", "") or "")
        return JSONResponse(runtime.debug_decisions(limit=limit, module=module, operation=operation))

    @mcp.custom_route("/api/v3/debug/decision/{identifier}", methods=["GET"])
    async def api_v3_debug_decision(request: Request) -> Response:
        from starlette.responses import JSONResponse

        err = sh._require_auth(request)
        if err:
            return err
        runtime = getattr(sh, "v3_runtime", None)
        identifier = str(request.path_params.get("identifier", ""))
        if runtime is None or not hasattr(runtime, "debug_decision"):
            return JSONResponse({"ok": False, "available": False, "error": "v3_runtime_unavailable"}, status_code=503)
        result = runtime.debug_decision(identifier)
        return JSONResponse(result, status_code=200 if result.get("ok") else 404)

    @mcp.custom_route("/api/v3/debug/replay/{identifier}", methods=["GET"])
    async def api_v3_debug_replay(request: Request) -> Response:
        from starlette.responses import JSONResponse

        err = sh._require_auth(request)
        if err:
            return err
        runtime = getattr(sh, "v3_runtime", None)
        identifier = str(request.path_params.get("identifier", ""))
        if runtime is None or not hasattr(runtime, "replay_decision"):
            return JSONResponse({"ok": False, "available": False, "error": "v3_runtime_unavailable"}, status_code=503)
        result = runtime.replay_decision(identifier)
        return JSONResponse(result, status_code=200 if result.get("record") else 404)


def _limit(value: object) -> int:
    try:
        return max(1, min(int(value), _MAX_LIMIT))
    except (TypeError, ValueError):
        return _DEFAULT_LIMIT
