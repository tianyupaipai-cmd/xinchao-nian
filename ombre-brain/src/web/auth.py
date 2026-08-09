"""
========================================
web/auth.py — Dashboard 鉴权相关 HTTP 路由
========================================

承载 /auth/* 这一组 cookie 会话鉴权接口（状态/首启设密/登录/登出/改密/安全问题急救）。
真正的会话/密码逻辑在 web/_shared.py，本文件只做 HTTP 入口与参数校验。

对外暴露：register(mcp) —— server.py 启动装配时调用，把下列路由挂到主 mcp 实例。
========================================
"""

import os

from starlette.requests import Request
from starlette.responses import Response

from . import _shared as sh

_MAX_PASSWORD_CHARS = 1024
_MAX_SECURITY_QUESTION_CHARS = 500
_MAX_SECURITY_ANSWER_CHARS = 1024


def _json_object(body) -> dict | None:
    return body if isinstance(body, dict) else None


def register(mcp) -> None:
    """把 /auth/* 路由注册到传入的 FastMCP 实例。"""

    @mcp.custom_route("/auth/status", methods=["GET"])
    async def auth_status(request: Request) -> Response:
        """Return auth state (authenticated, setup_needed)."""
        from starlette.responses import JSONResponse
        return JSONResponse({
            "authenticated": sh._is_authenticated(request),
            "setup_needed": sh._is_setup_needed(),
        })

    @mcp.custom_route("/auth/setup", methods=["POST"])
    async def auth_setup_endpoint(request: Request) -> Response:
        """Initial password setup (only when no password is configured)."""
        from starlette.responses import JSONResponse
        if not sh._is_setup_needed():
            return JSONResponse({"error": "Already configured"}, status_code=400)
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON"}, status_code=400)
        body = _json_object(body)
        if body is None:
            return JSONResponse({"error": "JSON body must be an object"}, status_code=400)
        password = body.get("password", "")
        if not isinstance(password, str):
            return JSONResponse({"error": "password must be a string"}, status_code=400)
        password = password.strip()
        if not 6 <= len(password) <= _MAX_PASSWORD_CHARS:
            return JSONResponse({"error": "密码长度必须在 6-1024 位之间"}, status_code=400)
        sh._save_password_hash(password)
        token = sh._create_session()
        resp = JSONResponse({"ok": True})
        sh._set_session_cookie(resp, token, request)
        return resp

    @mcp.custom_route("/auth/login", methods=["POST"])
    async def auth_login(request: Request) -> Response:
        """Login with password."""
        from starlette.responses import JSONResponse
        retry = sh._login_retry_after(request)
        if retry:
            return JSONResponse(
                {"error": f"尝试过于频繁，请 {retry} 秒后再试"},
                status_code=429,
                headers={"Retry-After": str(retry)},
            )
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON"}, status_code=400)
        body = _json_object(body)
        if body is None:
            sh._record_login_failure(request)
            return JSONResponse({"error": "JSON body must be an object"}, status_code=400)
        password = body.get("password", "")
        if not isinstance(password, str) or len(password) > _MAX_PASSWORD_CHARS:
            sh._record_login_failure(request)
            return JSONResponse({"error": "密码格式无效"}, status_code=400)
        if sh._verify_any_password(password):
            sh._record_login_success(request)
            token = sh._create_session()
            resp = JSONResponse({"ok": True})
            sh._set_session_cookie(resp, token, request)
            return resp
        sh._record_login_failure(request)
        return JSONResponse({"error": "密码错误"}, status_code=401)

    @mcp.custom_route("/auth/logout", methods=["POST"])
    async def auth_logout(request: Request) -> Response:
        """Invalidate session."""
        from starlette.responses import JSONResponse
        token = request.cookies.get("ombre_session")
        if token:
            sh._sessions.pop(token, None)
            sh._save_sessions()
        resp = JSONResponse({"ok": True})
        resp.delete_cookie("ombre_session")
        return resp

    @mcp.custom_route("/auth/change-password", methods=["POST"])
    async def auth_change_password(request: Request) -> Response:
        """Change dashboard password (requires current password)."""
        from starlette.responses import JSONResponse
        err = sh._require_auth(request)
        if err:
            return err
        if os.environ.get("OMBRE_DASHBOARD_PASSWORD", ""):
            return JSONResponse({"error": "当前使用环境变量密码，请直接修改 OMBRE_DASHBOARD_PASSWORD"}, status_code=400)
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON"}, status_code=400)
        body = _json_object(body)
        if body is None:
            return JSONResponse({"error": "JSON body must be an object"}, status_code=400)
        current = body.get("current", "")
        new_pwd = body.get("new", "")
        if not isinstance(current, str) or not isinstance(new_pwd, str):
            return JSONResponse({"error": "密码格式无效"}, status_code=400)
        new_pwd = new_pwd.strip()
        if len(current) > _MAX_PASSWORD_CHARS:
            return JSONResponse({"error": "当前密码格式无效"}, status_code=400)
        if not sh._verify_any_password(current):
            return JSONResponse({"error": "当前密码错误"}, status_code=401)
        if not 6 <= len(new_pwd) <= _MAX_PASSWORD_CHARS:
            return JSONResponse({"error": "新密码长度必须在 6-1024 位之间"}, status_code=400)
        sh._save_password_hash(new_pwd)
        sh._sessions.clear()
        sh._save_sessions()
        token = sh._create_session()
        resp = JSONResponse({"ok": True})
        sh._set_session_cookie(resp, token, request)
        return resp

    @mcp.custom_route("/auth/recovery-question", methods=["GET"])
    async def auth_recovery_question(request: Request) -> Response:
        """Return the configured security question (public, no auth needed)."""
        from starlette.responses import JSONResponse
        q = sh._load_auth_data().get("security_question", "")
        return JSONResponse({"question": q or None})

    @mcp.custom_route("/auth/recover", methods=["POST"])
    async def auth_recover(request: Request) -> Response:
        """Reset password via security question answer."""
        from starlette.responses import JSONResponse
        if os.environ.get("OMBRE_DASHBOARD_PASSWORD", ""):
            return JSONResponse({"error": "当前使用环境变量密码，无法通过安全问题重置"}, status_code=400)
        if not sh._load_auth_data().get("security_answer_hash"):
            return JSONResponse({"error": "未设置安全问题，无法使用急救模式"}, status_code=400)
        retry = sh._login_retry_after(request)
        if retry:
            return JSONResponse(
                {"error": f"尝试过于频繁，请 {retry} 秒后再试"},
                status_code=429,
                headers={"Retry-After": str(retry)},
            )
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON"}, status_code=400)
        body = _json_object(body)
        if body is None:
            sh._record_login_failure(request)
            return JSONResponse({"error": "JSON body must be an object"}, status_code=400)
        answer = body.get("answer", "")
        new_pwd = body.get("new_password", "")
        if not isinstance(answer, str) or not isinstance(new_pwd, str):
            sh._record_login_failure(request)
            return JSONResponse({"error": "恢复参数格式无效"}, status_code=400)
        new_pwd = new_pwd.strip()
        if len(answer) > _MAX_SECURITY_ANSWER_CHARS:
            sh._record_login_failure(request)
            return JSONResponse({"error": "答案格式无效"}, status_code=400)
        if not sh._verify_security_answer(answer):
            sh._record_login_failure(request)
            return JSONResponse({"error": "答案不正确"}, status_code=401)
        if not 6 <= len(new_pwd) <= _MAX_PASSWORD_CHARS:
            return JSONResponse({"error": "新密码长度必须在 6-1024 位之间"}, status_code=400)
        sh._record_login_success(request)
        sh._save_password_hash(new_pwd, keep_qa=True)
        sh._sessions.clear()
        sh._save_sessions()
        token = sh._create_session()
        resp = JSONResponse({"ok": True})
        sh._set_session_cookie(resp, token, request)
        return resp

    @mcp.custom_route("/auth/security-question", methods=["POST"])
    async def auth_set_security_question(request: Request) -> Response:
        """Set or update the security question (requires login)."""
        from starlette.responses import JSONResponse
        err = sh._require_auth(request)
        if err:
            return err
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON"}, status_code=400)
        body = _json_object(body)
        if body is None:
            return JSONResponse({"error": "JSON body must be an object"}, status_code=400)
        question = body.get("question", "")
        answer = body.get("answer", "")
        if not isinstance(question, str) or not isinstance(answer, str):
            return JSONResponse({"error": "问题和答案必须是字符串"}, status_code=400)
        question = question.strip()
        answer = answer.strip()
        if not question or not answer:
            return JSONResponse({"error": "问题和答案不能为空"}, status_code=400)
        if (
            len(question) > _MAX_SECURITY_QUESTION_CHARS
            or len(answer) > _MAX_SECURITY_ANSWER_CHARS
        ):
            return JSONResponse({"error": "问题或答案过长"}, status_code=400)
        sh._save_security_qa(question, answer)
        return JSONResponse({"ok": True})
