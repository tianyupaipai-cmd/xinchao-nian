"""
========================================
web/hooks.py — breath 浮现挂载点（HTTP hook）
========================================

- /breath-hook：对话开头由外部 hook 拉取，返回应浮现的记忆（pinned + 未解决采样）

不提供 /dream-hook：dream 按哲学不是义务、不该每次开场自动触发（详见下方端点处注释）。

给外部 SessionStart hook / 自动化用；默认需要 Dashboard 登录态或 hook token。
通过 sh.fire_webhook 推送事件。

对外暴露：register(mcp)。
========================================
"""

import hmac
import os
import random


from . import _shared as sh

logger = sh.logger

try:
    from utils import strip_wikilinks, count_tokens_approx, get_ai_name  # type: ignore
except ImportError:  # pragma: no cover
    from ..utils import strip_wikilinks, count_tokens_approx, get_ai_name  # type: ignore


def _truthy(value) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def _hook_setting(name: str, default=None):
    hooks_cfg = (getattr(sh, "config", {}) or {}).get("hooks") or {}
    return hooks_cfg.get(name, default)


def _header_value(request, name: str) -> str:
    headers = getattr(request, "headers", {}) or {}
    try:
        return str(headers.get(name, "") or "")
    except Exception:
        wanted = name.lower()
        for k, v in dict(headers).items():
            if str(k).lower() == wanted:
                return str(v or "")
    return ""


def _is_hook_request_authorized(request) -> bool:
    """Protect hook endpoints that can expose memory text.

    Public hooks can still be enabled deliberately with OMBRE_HOOK_ALLOW_PUBLIC=1
    or config hooks.allow_public=true. Otherwise a dashboard session or a hook
    token is required.
    """
    allow_public = _truthy(os.environ.get("OMBRE_HOOK_ALLOW_PUBLIC")) or _truthy(
        _hook_setting("allow_public")
    )
    if allow_public:
        return True

    token = (os.environ.get("OMBRE_HOOK_TOKEN") or str(_hook_setting("token", "") or "")).strip()
    if token:
        auth = _header_value(request, "authorization")
        supplied = [
            str((getattr(request, "query_params", {}) or {}).get("token", "") or ""),
            _header_value(request, "x-ombre-hook-token"),
            auth[7:] if auth.startswith("Bearer ") else "",
        ]
        if any(v and hmac.compare_digest(v, token) for v in supplied):
            return True

    try:
        return bool(sh._is_authenticated(request))
    except Exception:
        return False


def register(mcp) -> None:

    @mcp.custom_route("/breath-hook", methods=["GET"])
    async def breath_hook(request):
        from starlette.responses import PlainTextResponse
        if not _is_hook_request_authorized(request):
            return PlainTextResponse("", status_code=401)
        try:
            all_buckets = await sh.bucket_mgr.list_all(include_archive=False)
            # pinned
            pinned = [b for b in all_buckets if b["metadata"].get("pinned") or b["metadata"].get("protected")]
            # top 2 unresolved by score
            unresolved = [b for b in all_buckets
                          if not b["metadata"].get("resolved", False)
                          and b["metadata"].get("type") not in ("permanent", "feel", "plan", "letter", "self", "i")
                          and not b["metadata"].get("pinned")
                          and not b["metadata"].get("protected")
                          and not b["metadata"].get("dont_surface", False)]
            scored = sorted(unresolved, key=lambda b: sh.decay_engine.calculate_score(b["metadata"]), reverse=True)

            parts = []
            token_budget = 10000
            for b in pinned:
                summary = await sh.dehydrator.dehydrate(strip_wikilinks(b["content"]), {k: v for k, v in b["metadata"].items() if k != "tags"})
                parts.append(f"📌 [核心准则] {summary}")
                token_budget -= count_tokens_approx(summary)

            # Diversity: top-1 fixed + shuffle rest from top-20
            candidates = list(scored)
            if len(candidates) > 1:
                top1 = [candidates[0]]
                pool = candidates[1:min(20, len(candidates))]
                random.shuffle(pool)
                candidates = top1 + pool + candidates[min(20, len(candidates)):]
            # Hard cap: max 20 surfacing buckets in hook
            candidates = candidates[:20]

            for b in candidates:
                if token_budget <= 0:
                    break
                summary = await sh.dehydrator.dehydrate(strip_wikilinks(b["content"]), {k: v for k, v in b["metadata"].items() if k != "tags"})
                summary_tokens = count_tokens_approx(summary)
                if summary_tokens > token_budget:
                    break
                parts.append(summary)
                token_budget -= summary_tokens

            if not parts:
                await sh.fire_webhook("breath_hook", {"surfaced": 0})
                return PlainTextResponse("")
            body_text = "[Ombre Brain - 记忆浮现]\n" + "\n---\n".join(parts)

            # --- Append latest letter from each side (iter 1.4) ---
            # --- 附带双方各最新一封 letter ---
            try:
                letters = [b for b in all_buckets if b["metadata"].get("type") == "letter"]
                if letters:
                    def _latest(*authors: str) -> dict | None:
                        wanted = set(authors)
                        pool = [letter for letter in letters if letter["metadata"].get("author") in wanted]
                        if not pool:
                            return None
                        pool.sort(key=lambda b: b["metadata"].get("letter_date") or b["metadata"].get("created", ""), reverse=True)
                        return pool[0]
                    latest_user = _latest("user")
                    # AI 侧：新署名 ai_name + 历史遗留的 "claude"
                    latest_ai = _latest(get_ai_name(), "claude")
                    letter_lines = []
                    for tag, letter in (("user→你", latest_user), ("你→user", latest_ai)):
                        if letter is None:
                            continue
                        d = letter["metadata"].get("letter_date") or letter["metadata"].get("created", "")[:10]
                        title = letter["metadata"].get("title") or letter["metadata"].get("name", "")
                        excerpt = strip_wikilinks(letter["content"])[:400]
                        letter_lines.append(
                            f"💌 [{tag}] {d}{(' · ' + title) if title else ''}\n{excerpt}"
                        )
                    if letter_lines:
                        body_text += "\n\n=== 最近的信 ===\n" + "\n\n".join(letter_lines)
            except Exception as e:
                logger.warning(f"breath_hook letter section failed: {e}")

            # --- Append recent self-knowledge (I tool) ---
            try:
                self_buckets = [
                    b for b in all_buckets
                    if b["metadata"].get("type") == "i"
                    or "__i__" in (b["metadata"].get("tags") or [])
                ]
                if self_buckets:
                    self_buckets.sort(
                        key=lambda b: b["metadata"].get("created", ""), reverse=True
                    )
                    self_lines = []
                    for b in self_buckets[:3]:
                        meta = b["metadata"]
                        ts = (meta.get("created") or "")[:10]
                        tags_list = meta.get("tags") or []
                        aspect_tag = next(
                            (t.replace("aspect:", "") for t in tags_list if t.startswith("aspect:")), ""
                        )
                        aspect_label = f" [{aspect_tag}]" if aspect_tag else ""
                        excerpt = strip_wikilinks(b["content"])[:300]
                        self_lines.append(f"🪞{ts}{aspect_label}\n{excerpt}")
                    if self_lines:
                        body_text += "\n\n=== I ===\n" + "\n\n".join(self_lines)
            except Exception as e:
                logger.warning(f"breath_hook I section failed: {e}")

            await sh.fire_webhook("breath_hook", {"surfaced": len(parts), "chars": len(body_text)})
            return PlainTextResponse(body_text)
        except Exception as e:
            logger.warning(f"Breath hook failed: {e}")
            return PlainTextResponse("")

    # 注意：这里**故意不再提供 /dream-hook**。
    # 按 OB 的设计哲学，dream（做梦消化）不是义务、不该在每次会话开始被自动触发——
    # 它只应在「需要消化时」由模型主动调用 MCP 的 dream 工具。把它做成 SessionStart hook
    # 会把「主动消化」异化成「每次开场的强制动作」，与哲学冲突，故移除该端点。
