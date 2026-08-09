"""
========================================
web/letters.py — 信件（letter）读写
========================================

- /api/letters：列出信件
- /api/letter (POST)：写信
- /letters：信件页（兼容入口）
- /api/letter/{id} (PATCH/DELETE)：编辑 / 删除信件

对外暴露：register(mcp)。
========================================
"""

from starlette.requests import Request
from starlette.responses import Response

from . import _shared as sh
from tools._common import check_content_size, check_metadata_size

try:
    from utils import strip_wikilinks, get_ai_name  # type: ignore
except ImportError:  # pragma: no cover
    from ..utils import strip_wikilinks, get_ai_name  # type: ignore


def _normalize_author(raw: str) -> str:
    """把传入署名归一化为存储值，与 tools/plan/core.letter_write 同一套规则：
    "user"→"user"；"ai"/"claude"(历史)/等于 ai_name→ai_name 的值；其它原样。"""
    raw = (raw or "").strip()
    if not raw:
        return ""
    ai = get_ai_name()
    low = raw.lower()
    if low == "user":
        return "user"
    if low in ("ai", "claude") or raw == ai:
        return ai
    return raw


def register(mcp) -> None:

    @mcp.custom_route("/api/letters", methods=["GET"])
    async def api_letters(request: Request) -> Response:
        """List all letters, newest first. Supports ?author=user|ai|<署名> filter."""
        from starlette.responses import JSONResponse
        err = sh._require_auth(request)
        if err:
            return err
        author = request.query_params.get("author", "").strip()
        metadata_error = check_metadata_size(author=author)
        if metadata_error:
            return JSONResponse({"error": metadata_error}, status_code=400)
        try:
            all_b = await sh.bucket_mgr.list_all(include_archive=False)
            letters = [b for b in all_b if b["metadata"].get("type") == "letter"]
            if author:
                af_low = author.lower()
                if af_low == "user":
                    letters = [b for b in letters if b["metadata"].get("author") == "user"]
                elif af_low in ("ai", "claude") or author == get_ai_name():
                    ai_aliases = {get_ai_name(), "claude"}
                    letters = [b for b in letters if b["metadata"].get("author") in ai_aliases]
                else:
                    letters = [b for b in letters if b["metadata"].get("author") == author]
            letters.sort(
                key=lambda b: b["metadata"].get("letter_date") or b["metadata"].get("created", ""),
                reverse=True,
            )
            result = []
            for b in letters:
                m = b["metadata"]
                result.append({
                    "id": b["id"],
                    "author": m.get("author", ""),
                    "user_name": m.get("user_name", ""),
                    "title": m.get("title", "") or m.get("name", ""),
                    "date": m.get("letter_date") or m.get("created", "")[:10],
                    "created": m.get("created", ""),
                    "content": strip_wikilinks(b.get("content", "")),
                })
            return JSONResponse({"letters": result, "total": len(result)})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)


    @mcp.custom_route("/api/letter", methods=["POST"])
    async def api_letter_create(request: Request) -> Response:
        """Create a letter from the dashboard."""
        from starlette.responses import JSONResponse
        err = sh._require_auth(request)
        if err:
            return err
        try:
            body = await sh._read_json_object(request)
        except Exception:
            return JSONResponse({"error": "invalid JSON"}, status_code=400)
        string_fields = ("author", "content", "user_name", "title", "date", "ai_name")
        if any(key in body and not isinstance(body[key], str) for key in string_fields):
            return JSONResponse({"error": "letter fields must be strings"}, status_code=400)
        raw_author = (body.get("author") or "").strip()
        content = (body.get("content") or "").strip()
        if not raw_author:
            return JSONResponse({"error": "author required"}, status_code=400)
        if not content:
            return JSONResponse({"error": "content required"}, status_code=400)
        size_err = check_content_size(content)
        if size_err:
            return JSONResponse({"error": size_err}, status_code=400)
        metadata_err = check_metadata_size(
            author=raw_author,
            user_name=body.get("user_name", ""),
            title=body.get("title", ""),
            date=body.get("date", ""),
            ai_name=body.get("ai_name", ""),
        )
        if metadata_err:
            return JSONResponse({"error": metadata_err}, status_code=400)
        # ai_name：请求体显式传入优先，否则取环境变量 AI_NAME（回退 "AI"）。
        ai = (body.get("ai_name") or "").strip() or get_ai_name()
        low = raw_author.lower()
        if low == "user":
            author = "user"
        elif low in ("ai", "claude") or raw_author == ai:
            author = ai
        else:
            author = raw_author
        user_name = (body.get("user_name") or "").strip()
        title = (body.get("title") or "").strip()[:120]
        date = (body.get("date") or "").strip()
        extra = {"author": author}
        if user_name:
            extra["user_name"] = user_name
        if title:
            extra["title"] = title
        if date:
            extra["letter_date"] = date
        try:
            bid = await sh.bucket_mgr.create(
                content=content,
                tags=["__letter__"],
                importance=10,
                domain=["letter"],
                valence=0.5,
                arousal=0.3,
                name=(title[:60] or f"{author}_{date or 'letter'}"),
                bucket_type="letter",
                source_tool="letter",
            )
            await sh.bucket_mgr.update(bid, **extra)
            return JSONResponse({"ok": True, "id": bid})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)


    @mcp.custom_route("/letters", methods=["GET"])
    async def letters_page(request: Request) -> Response:
        """Legacy alias: /letters 永久跳到 dashboard 的「信」分页。

        我把 letters 合并进 dashboard 的一个 tab 后，这条老路径只保留 301 软迁移，
        避免独立维护两套 HTML/JS。
        """
        from starlette.responses import RedirectResponse
        return RedirectResponse(url="/#letters", status_code=301)


    @mcp.custom_route("/api/letter/{letter_id}", methods=["PATCH"])
    async def api_letter_edit(request: Request) -> Response:
        """Edit an existing letter (content / title / author / date / user_name)."""
        from starlette.responses import JSONResponse
        err = sh._require_auth(request)
        if err:
            return err
        letter_id = request.path_params["letter_id"]
        bucket = await sh.bucket_mgr.get(letter_id)
        if not bucket or bucket["metadata"].get("type") != "letter":
            return JSONResponse({"error": "letter not found"}, status_code=404)
        try:
            body = await sh._read_json_object(request)
        except Exception:
            return JSONResponse({"error": "invalid JSON"}, status_code=400)

        editable_string_fields = ("content", "title", "author", "user_name", "date")
        if any(
            key in body and not isinstance(body[key], str)
            for key in editable_string_fields
        ):
            return JSONResponse({"error": "letter fields must be strings"}, status_code=400)
        updates: dict = {}
        if "content" in body and isinstance(body["content"], str) and body["content"].strip():
            size_err = check_content_size(body["content"])
            if size_err:
                return JSONResponse({"error": size_err}, status_code=400)
            updates["content"] = body["content"].strip()
        if "title" in body and isinstance(body["title"], str):
            updates["title"] = body["title"].strip()[:120]
        if "author" in body:
            a = _normalize_author(str(body["author"]))
            if a:
                updates["author"] = a
        if "user_name" in body and isinstance(body["user_name"], str):
            updates["user_name"] = body["user_name"].strip()
        if "date" in body and isinstance(body["date"], str):
            updates["letter_date"] = body["date"].strip()

        if not updates:
            return JSONResponse({"error": "nothing to update"}, status_code=400)

        try:
            ok = await sh.bucket_mgr.update(letter_id, **updates)
            if not ok:
                return JSONResponse({"error": "update failed"}, status_code=500)
            if "content" in updates:
                try:
                    sh.dehydrator.invalidate_cache(bucket["content"])
                except Exception:
                    pass
            return JSONResponse({"ok": True, "id": letter_id, "updated": list(updates.keys())})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)


    @mcp.custom_route("/api/letter/{letter_id}", methods=["DELETE"])
    async def api_letter_delete(request: Request) -> Response:
        """Delete a letter to archive. Requires ?confirm=true."""
        from starlette.responses import JSONResponse
        err = sh._require_auth(request)
        if err:
            return err
        if request.query_params.get("confirm", "").lower() not in ("true", "1", "yes"):
            return JSONResponse({"error": "confirm=true required for delete-to-archive"}, status_code=400)
        letter_id = request.path_params["letter_id"]
        bucket = await sh.bucket_mgr.get(letter_id)
        if bucket and bucket["metadata"].get("type") != "letter":
            return JSONResponse({"error": "letter not found"}, status_code=404)
        try:
            # Idempotent repair for a half-deleted letter: the Markdown file may
            # already be gone while the active cache/vector still exposes it.
            # Archive a real letter when present, then independently clean every
            # derived layer even when no file remains.
            archived = bool(bucket) and await sh.bucket_mgr.delete(letter_id)
            if bucket and not archived:
                return JSONResponse({"error": "letter archive failed"}, status_code=500)
            outbox = getattr(sh.bucket_mgr, "embedding_outbox", None)
            if outbox is not None:
                try:
                    outbox.discard(letter_id)
                except Exception:
                    pass
            try:
                sh.embedding_engine.delete_embedding(letter_id)
            except Exception:
                pass
            invalidate = getattr(sh.bucket_mgr, "_invalidate_bm25", None)
            if callable(invalidate):
                invalidate()
            return JSONResponse({
                "ok": True,
                "deleted": archived,
                "cleaned": True,
                "already_missing": not bool(bucket),
            })
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)
