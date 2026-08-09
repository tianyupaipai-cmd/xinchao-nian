"""
Ombre Brain — 统一错误码体系 / Unified Error Code System
==========================================================

设计原则（来自 rule.md §1.5 +  2026-05-02 规范）：
    "在产生与发现错误这件事上，能说出来的绝不静默。"
    "报错要让她/他在前端面板上能看到，也要让 LLM 模型在 MCP 的返回端看到。"

四级严重度：
    F (Fatal)   — 拒绝启动 + 终端输出 + 写 error.log
    E (Error)   — 前端弹窗 + MCP 返回值末尾 + 附最近 15 条 log
    W (Warning) — MCP 返回值末尾追加 + 前端日志面板
    I (Info)    — MCP 返回值末尾追加（轻量提示，例如自动降级）

模块职责：
    1. ERROR_CODES：错误码注册表（含级别、中英文描述、建议操作）
    2. format_error()：标准化字符串渲染
    3. record_error()：写持久化 errors.jsonl + 内存 buffer
    4. recent_errors()：供 /api/errors/recent 端点读取
    5. log_buffer：环形缓冲，存最近 N 条 log（含 stderr 流过的所有 log）
    6. attach_log_buffer_handler()：把 BufferHandler 装到 root logger
    7. warnings_channel（contextvars）：MCP 工具调用期间累积的 W/I 提示，
       由 _with_notice() 在工具返回前 pop 出并 append 到返回值末尾

不引入任何额外依赖，纯标准库实现。
"""
from __future__ import annotations

import collections
import contextvars
import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Iterable

logger = logging.getLogger(__name__)


# ============================================================
# 1. 错误码表 / Error Code Registry
# ============================================================

@dataclass(frozen=True)
class ErrorSpec:
    code: str            # e.g. "OB-E001"
    level: str           # "F" | "E" | "W" | "I"
    title_zh: str
    title_en: str
    suggestion_zh: str
    suggestion_en: str = ""


# 注册表 —— 修改/新增请同时同步 rule.md §11
ERROR_CODES: dict[str, ErrorSpec] = {
    # ---- Fatal：拒绝启动 ----
    "OB-F001": ErrorSpec(
        code="OB-F001",
        level="F",
        title_zh="向量化 API Key 缺失",
        title_en="Embedding API key missing",
        suggestion_zh=(
            "设置环境变量 OMBRE_EMBED_API_KEY（或在 config.yaml 中填写 embedding.api_key）。\n"
            "若暂时不需要语义检索，可在 config.yaml 中设置 embedding.enabled=false 跳过。"
        ),
    ),
    "OB-F002": ErrorSpec(
        code="OB-F002",
        level="F",
        title_zh="config.yaml 损坏或缺失",
        title_en="config.yaml missing or malformed",
        suggestion_zh=(
            "检查项目根目录是否存在 config.yaml；如缺失，从 config.example.yaml 复制一份。"
            "如已存在，运行 `python -c \"import yaml; yaml.safe_load(open('config.yaml'))\"` 看是否能解析。"
        ),
    ),
    "OB-F003": ErrorSpec(
        code="OB-F003",
        level="F",
        title_zh="vault 目录不可写",
        title_en="vault (buckets) directory not writable",
        suggestion_zh=(
            "检查 OMBRE_BUCKETS_DIR 指向的目录是否存在且当前用户拥有写权限。"
            "Docker 部署请检查 volume 挂载与 uid/gid 映射。"
        ),
    ),
    "OB-F004": ErrorSpec(
        code="OB-F004",
        level="F",
        title_zh="embedding 后端初始化失败",
        title_en="Embedding backend initialization failed",
        suggestion_zh=(
            "检查 OMBRE_EMBED_API_KEY 是否有效，以及 OMBRE_EMBED_BASE_URL 是否可达。"
        ),
    ),

    # ---- Error：前端弹窗 + MCP 末尾 ----
    "OB-E001": ErrorSpec(
        code="OB-E001",
        level="E",
        title_zh="embedding API 调用失败",
        title_en="Embedding API call failed",
        suggestion_zh=(
            "检查网络可达性、OMBRE_EMBED_API_KEY 是否有效、配额是否耗尽。"
            "本次写入仍会保存到 buckets，向量由后台自动重试；也可调用 "
            "/api/embedding/backfill 手动触发全库对账。"
        ),
    ),
    "OB-E002": ErrorSpec(
        code="OB-E002",
        level="E",
        title_zh="写盘失败",
        title_en="Disk write failed",
        suggestion_zh=(
            "检查磁盘剩余空间、目录权限；确认未被备份/同步软件锁定（iCloud/Dropbox 等）。"
        ),
    ),
    "OB-E003": ErrorSpec(
        code="OB-E003",
        level="E",
        title_zh="并发冲突超时",
        title_en="Concurrency lock timeout",
        suggestion_zh=(
            "同一 content 的 merge_or_create 长时间未释放锁；通常是上一个调用卡死。"
            "稍后重试；若反复出现，重启服务或检查 LLM 提供方是否慢响应。"
        ),
    ),
    "OB-E004": ErrorSpec(
        code="OB-E004",
        level="E",
        title_zh="MCP 工具执行异常",
        title_en="MCP tool execution exception",
        suggestion_zh=(
            "查看下方异常详情与最近 15 条日志定位根因。"
            "若是参数问题，按提示修正；若是后端故障，请重试或反馈。"
        ),
    ),

    # ---- Warning：MCP 返回末尾 + 前端日志面板 ----
    "OB-W001": ErrorSpec(
        code="OB-W001",
        level="W",
        title_zh="importance 越界已修正",
        title_en="importance out of range, clamped",
        suggestion_zh="importance 必须在 [1,10]；本次已被修正到边界值。",
    ),
    "OB-W002": ErrorSpec(
        code="OB-W002",
        level="W",
        title_zh="valence/arousal 越界已回退",
        title_en="valence/arousal out of range, clamped",
        suggestion_zh="valence/arousal 必须在 [0.0, 1.0]；本次已被修正到边界值。",
    ),
    "OB-W003": ErrorSpec(
        code="OB-W003",
        level="W",
        title_zh="importance≥9 配额接近上限",
        title_en="importance≥9 quota near cap",
        suggestion_zh=(
            "标为 importance≥9 的桶接近上限（22/24，硬上限 24）。"
            "建议先用 trace(bucket_id, importance=…) 把不再核心的旧桶降级，再标新桶。"
        ),
    ),
    "OB-W004": ErrorSpec(
        code="OB-W004",
        level="W",
        title_zh="pinned 配额接近上限",
        title_en="pinned quota near cap",
        suggestion_zh=(
            "pinned 桶接近上限（默认 18/20，硬上限 20，可在 config.limits.max_pinned 调整）。"
            "建议先用 trace(bucket_id, pinned=0) 取消不再核心的钉选，再钉新桶。"
        ),
    ),
    "OB-W005": ErrorSpec(
        code="OB-W005",
        level="W",
        title_zh="embeddings.db 中的模型/维度与当前后端不一致",
        title_en="embeddings.db model/dim mismatch with current backend",
        suggestion_zh=(
            "过往写入的向量与当前模型不同维，搜索会退化为 0 分。"
            "请在 Dashboard 设置页点击「切换模型」，或调用 POST /api/embedding/migrate 重建索引。"
            "迁移期间搜索降级为关键词模式，不会丢文件。"
        ),
    ),

    # ---- Info：自动降级 / 轻量提示 ----
    "OB-I001": ErrorSpec(
        code="OB-I001",
        level="I",
        title_zh="importance 已自动降级（importance≥9 配额超标）",
        title_en="importance auto-downgraded (≥9 quota exceeded)",
        suggestion_zh=(
            "★ 这是 OB 自作主张帮你做的事 ★\n"
            "importance≥9 的桶已达硬上限 24，本次新桶被自动降级为 importance=8。\n"
            "建议：用 breath(importance_min=9) 重读全部「核心事项」，"
            "重新评估每条 importance；不再核心的用 trace(bucket_id, importance=7) 降级。\n"
            "（重新设定 importance 的责任在你，OB 不会替你判断哪条更重要。）"
        ),
    ),
    "OB-I002": ErrorSpec(
        code="OB-I002",
        level="I",
        title_zh="pinned 已自动退出（pinned 配额超标）",
        title_en="pinned auto-unset (pinned quota exceeded)",
        suggestion_zh=(
            "★ 这是 OB 自作主张帮你做的事 ★\n"
            "pinned 桶已达硬上限（默认 20，可在 config.limits.max_pinned 调整），本次未钉成功（保留为普通桶）。\n"
            "建议：用 breath 看一遍当前 pinned 列表，把不再属于「永久核心准则」的"
            "用 trace(bucket_id, pinned=0) 取消，再来钉这条。"
        ),
    ),
}

# ImportError 等：在调用方 raise OBStartupError 时使用
ALL_LEVELS = ("F", "E", "W", "I")


# ============================================================
# 2. 内存日志环形缓冲 / In-memory Log Ring Buffer
# ============================================================

_LOG_BUFFER_MAX = 500     # 总环形缓冲，前端"最近日志"读这里
_LOG_TAIL_FOR_ERROR = 15  # E 级报错附带的最近日志条数（按规范）

_log_buffer: collections.deque[str] = collections.deque(maxlen=_LOG_BUFFER_MAX)
_log_buffer_lock = threading.Lock()


class _BufferHandler(logging.Handler):
    """把 logging 输出顺手存一份到内存 deque，供 E 级报错附带 tail。"""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
            with _log_buffer_lock:
                _log_buffer.append(line)
        except Exception:
            # 日志 handler 自己绝不能抛
            pass


def attach_log_buffer_handler(level: int = logging.INFO) -> None:
    """把 BufferHandler 挂到 root logger；幂等，重复调用无害。"""
    root = logging.getLogger()
    for h in root.handlers:
        if isinstance(h, _BufferHandler):
            return
    h = _BufferHandler()
    h.setLevel(level)
    h.setFormatter(logging.Formatter(
        "[%(asctime)s] %(name)s %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    root.addHandler(h)


def get_recent_logs(n: int = _LOG_TAIL_FOR_ERROR) -> list[str]:
    """读取最近 n 条 log（newest last）。"""
    with _log_buffer_lock:
        if n >= len(_log_buffer):
            return list(_log_buffer)
        return list(_log_buffer)[-n:]


# ============================================================
# 3. 持久化错误日志 / Persistent Error Log
# ============================================================

_errors_path: str | None = None
_errors_path_lock = threading.Lock()


def configure_errors_path(buckets_dir: str) -> None:
    """由 server 启动时调用：将 errors.jsonl 放在 buckets_dir/.logs/errors.jsonl。"""
    global _errors_path
    log_dir = os.path.join(buckets_dir, ".logs")
    try:
        os.makedirs(log_dir, exist_ok=True)
        _errors_path = os.path.join(log_dir, "errors.jsonl")
    except Exception as e:
        logger.warning(f"[errors] cannot create log dir {log_dir}: {e}")
        _errors_path = None


def _persist_error_record(record: dict) -> None:
    if not _errors_path:
        return
    try:
        with _errors_path_lock:
            with open(_errors_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning(f"[errors] persist failed: {e}")


def recent_errors(limit: int = 50, min_level: str = "W") -> list[dict]:
    """读取最近 limit 条已记录的错误（从 errors.jsonl 末尾倒序取）。"""
    if not _errors_path or not os.path.exists(_errors_path):
        return []
    order = ["I", "W", "E", "F"]
    if min_level not in order:
        min_level = "W"
    min_idx = order.index(min_level)
    try:
        with open(_errors_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception as e:
        logger.warning(f"[errors] read failed: {e}")
        return []
    out: list[dict] = []
    for ln in reversed(lines):
        ln = ln.strip()
        if not ln:
            continue
        try:
            obj = json.loads(ln)
        except Exception:
            continue
        lvl = obj.get("level", "W")
        if lvl in order and order.index(lvl) >= min_idx:
            out.append(obj)
        if len(out) >= limit:
            break
    return out


def clear_errors_log() -> int:
    """清空 errors.jsonl，返回原行数（供 dashboard "已读" 按钮）。"""
    if not _errors_path or not os.path.exists(_errors_path):
        return 0
    try:
        with _errors_path_lock:
            with open(_errors_path, "r", encoding="utf-8") as f:
                n = sum(1 for _ in f)
            open(_errors_path, "w", encoding="utf-8").close()
        return n
    except Exception as e:
        logger.warning(f"[errors] clear failed: {e}")
        return 0


# ============================================================
# 4. 标准格式化 / Standard Formatter
# ============================================================

_LEVEL_PREFIX = {
    "F": "🛑",   # Fatal
    "E": "❌",   # Error
    "W": "⚠️",   # Warning
    "I": "ℹ️",   # Info
}


def format_error(
    code: str,
    detail: str = "",
    *,
    include_logs: bool | None = None,
    extra: dict | None = None,
) -> str:
    """渲染统一格式字符串。

    include_logs=None 时按级别决定：F/E 默认带 tail，W/I 默认不带。
    """
    spec = ERROR_CODES.get(code)
    if not spec:
        # 未知码：仍能渲染，让排错时一眼看到拼错的码
        return (
            f"❌ [{code}] 未注册错误码\n"
            f"详情：{detail}\n"
            f"建议：在 src/errors.py ERROR_CODES 注册该码或修正调用处。"
        )
    prefix = _LEVEL_PREFIX.get(spec.level, "•")
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    parts = [
        f"{prefix} [{spec.code}] {spec.title_zh}",
    ]
    if detail:
        parts.append(f"描述：{detail}")
    parts.append(f"建议：{spec.suggestion_zh}")
    parts.append(f"时间：{ts}")
    if extra:
        for k, v in extra.items():
            parts.append(f"{k}：{v}")

    if include_logs is None:
        include_logs = spec.level in ("F", "E")
    if include_logs:
        tail = get_recent_logs(_LOG_TAIL_FOR_ERROR)
        parts.append("")
        parts.append(f"--- 最近 {len(tail)} 条日志 ---")
        parts.extend(tail if tail else ["(暂无日志)"])
    return "\n".join(parts)


def record_error(
    code: str,
    detail: str = "",
    *,
    extra: dict | None = None,
    log: bool = True,
) -> dict:
    """记录一条错误：写 errors.jsonl + 同步到 logger（按级别）+ 返回结构化 dict。

    上层若需要把它附加到 MCP 返回值，使用 format_error 或 push_warning。
    """
    spec = ERROR_CODES.get(code)
    level = spec.level if spec else "E"
    record = {
        "code": code,
        "level": level,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "title": spec.title_zh if spec else "未注册错误码",
        "detail": detail,
        "extra": extra or {},
    }
    _persist_error_record(record)
    if log:
        msg = f"[{code}] {record['title']} | {detail}"
        if level == "F":
            logger.critical(msg)
        elif level == "E":
            logger.error(msg)
        elif level == "W":
            logger.warning(msg)
        else:
            logger.info(msg)
    return record


# ============================================================
# 5. MCP 返回值警告通道 / MCP Return Suffix Channel
# ============================================================
#
# 设计：MCP 工具调用期间，业务代码（bucket_manager / tools/_common 等）可能在
# 任意层产生 W/I 级提示。这些提示要透传到 MCP 返回值末尾让 AI 能看到。
# 用 contextvars 维护一个 per-task 的列表；server.py 的 _with_notice 包装器
# 在工具返回时 pop 出来 append 到末尾。
# 注意：contextvars 在 asyncio 中按任务隔离，不会跨调用串味。

_warnings_var: contextvars.ContextVar[list[str] | None] = contextvars.ContextVar(
    "ob_warnings", default=None
)


def begin_warnings() -> None:
    """在每次 MCP 工具调用入口处调用一次，初始化本调用的 channel。"""
    _warnings_var.set([])


def push_warning(code: str, detail: str = "", *, extra: dict | None = None) -> None:
    """业务代码调用：登记一条 W/I 级提示。

    会同时 record_error（写盘 + 写 logger）。
    """
    record_error(code, detail, extra=extra)
    cur = _warnings_var.get()
    if cur is None:
        # 调用方不在 MCP 工具上下文（例如后台任务），仅持久化即可
        return
    cur.append(format_error(code, detail, extra=extra))


def pop_warnings() -> list[str]:
    """server.py 的 _with_notice 在工具返回前调用，取出本调用累计的提示。"""
    cur = _warnings_var.get()
    if cur is None:
        return []
    _warnings_var.set([])
    return cur


def format_warnings_suffix(warnings: Iterable[str]) -> str:
    items = list(warnings)
    if not items:
        return ""
    return "\n\n" + "\n\n".join(items)


# ============================================================
# 6. 启动期专用异常 / Startup-time Exception
# ============================================================

class OBStartupError(SystemExit):
    """Fatal：拒绝启动。携带错误码，由 server.py 顶层捕获后输出标准格式 + 写 error.log。

    注意：SystemExit 自身有内置 ``.code`` 属性（保存进程退出码），所以本类用
    ``.error_code`` 暴露 OB 错误码；同时也提供 ``.code`` 的兼容别名。
    """

    def __init__(self, code: str, detail: str = "", *, extra: dict | None = None):
        self.error_code = code
        self.detail = detail
        self.extra = extra or {}
        # SystemExit 的 message 即终端最终输出
        msg = format_error(code, detail, extra=extra, include_logs=True)
        super().__init__(msg)


def write_fatal_log(code: str, detail: str, *, buckets_dir: str | None = None) -> None:
    """Fatal 级别专用：直接写 error.log（不走 errors.jsonl 因为可能尚未 configure）。"""
    target_dir = buckets_dir or os.environ.get("OMBRE_BUCKETS_DIR", "").strip() or "."
    try:
        log_dir = os.path.join(target_dir, ".logs")
        os.makedirs(log_dir, exist_ok=True)
        with open(os.path.join(log_dir, "error.log"), "a", encoding="utf-8") as f:
            f.write(format_error(code, detail, include_logs=True) + "\n\n")
    except Exception:
        pass


__all__ = [
    "ERROR_CODES",
    "ErrorSpec",
    "format_error",
    "record_error",
    "recent_errors",
    "clear_errors_log",
    "configure_errors_path",
    "get_recent_logs",
    "attach_log_buffer_handler",
    "begin_warnings",
    "push_warning",
    "pop_warnings",
    "format_warnings_suffix",
    "OBStartupError",
    "write_fatal_log",
]
