"""
========================================
import_memory.py — 历史对话导入引擎
========================================

把各平台导出的历史对话（Claude JSON / ChatGPT / DeepSeek / Markdown / 纯文本）
切块、过LLM 打标、写入记忆系统。

关键行为：
- 自动识别格式，分块处理，单 chunk 独立成桶
- 导入进度持久化到 import_state.json，可断点续传
- raw 模式：保留原文不脱水，给特殊场景用
- 导入完成后扫一遍频次模式（同一主题反复出现 → 提示她/他 pin）

不做什么（边界）：
- 不在线接收对话流（只处理离线导出文件）
- 不写桶文件本身（委托给 BucketManager）
- 不调用 dehydrator.merge（只新建，不合并）

对外暴露：ImportEngine 类（被 server.py 注入到 _runtime，由 dashboard API 触发）
========================================
"""

import os
import json
import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from utils import clean_llm_json, count_tokens_approx, now_iso, parse_bool

logger = logging.getLogger("ombre_brain.import")


# ============================================================
# 调参面板 / Tunable constants
# ------------------------------------------------------------
# rule.md §①：禁裸魔法数字。导入流水线上下参数集中定义在这里。
# ============================================================

# --- chunk_turns：对话轮次分窗 ---
_CHUNK_TARGET_TOKENS = 10000   # 单个 chunk 目标 token 数
_CHUNK_OVERSIZE_RATIO = 1.5    # 单轮 × 该倍数 → 单独成 chunk（避免超范围）

# --- ImportState ---
_STATE_HASH_HEX = 16           # source_hash 取 sha256 前 16 hex
_STATE_ERR_LOG_MAX = 100       # errors 数组最多保留条数（避免状态文件肨胀）
_CHUNK_ERR_PREVIEW = 200       # 单 chunk 错误信息截断长度

# --- _extract_memories LLM 调用 ---
_EXTRACT_INPUT_LIMIT = 12000   # chunk 内容传给 LLM 的上限
_EXTRACT_MAX_TOKENS = 2048
_EXTRACT_TEMPERATURE = 0.0     # 提取需确定性
_PARSE_ERR_PREVIEW = 200       # JSON 解析失败时日志预览

# --- 默认情感坐标与 importance（与 dehydrator 保持一致）---
_DEFAULT_VALENCE = 0.5
_DEFAULT_AROUSAL = 0.3
_DEFAULT_IMPORTANCE = 5
_IMPORTANCE_MIN = 1
_IMPORTANCE_MAX = 10

# --- 输出截断长度 ---
_NAME_MAX_CHARS = 20
_DOMAIN_MAX = 3
_TAGS_MAX = 10                 # extraction 试在 10 个以内（与 dehydrator 的 15 不同，导入场景信息密度较低）

# --- merge_or_create 默认阈值 ---
_DEFAULT_MERGE_THRESHOLD = 75

# --- detect_patterns：embedding 聚类 ---
_PATTERN_MIN_DYNAMIC_BUCKETS = 5  # 动态桶少于该数 → 不作处理
_PATTERN_SIMILARITY_THRESHOLD = 0.7  # 两桶向量余弦 > 该值 → 归同一类
_PATTERN_MIN_CLUSTER_SIZE = 3     # 类内成员 ≥ 该数才认为是“高频模式”
_PATTERN_PIN_SUGGEST_THRESHOLD = 5  # 成员 ≥ 该数 → 建议 pin，否则仅 review
_PATTERN_RESULT_LIMIT = 20        # 返回给 dashboard 的 pattern 上限
_PATTERN_CONTENT_PREVIEW = 200    # pattern_content 预览长度


def _clamp_va(meta: dict) -> tuple[float, float]:
    """将 meta 中的 valence / arousal 钳制到 [0, 1]。

    与 dehydrator._clamp_va 同表现，这里单独复制一份是为了避免
    import_memory 反向依赖 dehydrator 的私有方法。两者默认值一致（
    rule.md §1.0 哲学：中性 V=0.5 / 低唤醒 A=0.3）。
    """
    try:
        v = max(0.0, min(1.0, float(meta.get("valence", _DEFAULT_VALENCE))))
        a = max(0.0, min(1.0, float(meta.get("arousal", _DEFAULT_AROUSAL))))
        return v, a
    except (ValueError, TypeError):
        return _DEFAULT_VALENCE, _DEFAULT_AROUSAL


def _clamp_importance(meta: dict) -> int:
    """将 meta.importance 钳制到 [1, 10]。解析失败返回默认 5。"""
    try:
        return max(
            _IMPORTANCE_MIN,
            min(_IMPORTANCE_MAX, int(meta.get("importance", _DEFAULT_IMPORTANCE))),
        )
    except (ValueError, TypeError):
        return _DEFAULT_IMPORTANCE


def _strip_md_fence(raw: str) -> str:
    """Backwards-compatible wrapper for tolerant LLM JSON extraction."""
    return clean_llm_json(raw)


# ============================================================
# Format Parsers — normalize any format to conversation turns
# 格式解析器 — 将任意格式标准化为对话轮次
# ============================================================

def _parse_claude_json(data: dict | list) -> list[dict]:
    """Parse Claude.ai export JSON → [{role, content, timestamp}, ...]"""
    turns = []
    conversations = data if isinstance(data, list) else [data]
    for conv in conversations:
        if not isinstance(conv, dict):
            continue
        messages = conv.get("chat_messages", conv.get("messages", []))
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            content = msg.get("text", msg.get("content", ""))
            if isinstance(content, list):
                content = " ".join(
                    p.get("text", "") for p in content if isinstance(p, dict)
                )
            if not content or not content.strip():
                continue
            role = msg.get("sender", msg.get("role", "user"))
            ts = msg.get("created_at", msg.get("timestamp", ""))
            turns.append({"role": role, "content": content.strip(), "timestamp": ts})
    return turns


def _parse_chatgpt_json(data: list | dict) -> list[dict]:
    """Parse ChatGPT export JSON → [{role, content, timestamp}, ...]"""
    turns = []
    conversations = data if isinstance(data, list) else [data]
    for conv in conversations:
        if not isinstance(conv, dict):
            continue
        mapping = conv.get("mapping", {})
        if mapping:
            # ChatGPT uses a tree structure with mapping
            # Filter out None nodes before sorting
            valid_nodes = [n for n in mapping.values() if isinstance(n, dict)]

            def _node_ts(n):
                msg = n.get("message")
                if not isinstance(msg, dict):
                    return 0
                return msg.get("create_time") or 0

            sorted_nodes = sorted(valid_nodes, key=_node_ts)
            for node in sorted_nodes:
                msg = node.get("message")
                if not msg or not isinstance(msg, dict):
                    continue
                content_obj = msg.get("content", {})
                content_parts = content_obj.get("parts", []) if isinstance(content_obj, dict) else []
                content = " ".join(str(p) for p in content_parts if p)
                if not content.strip():
                    continue
                role = (msg.get("author") or {}).get("role", "user")
                ts = msg.get("create_time", "")
                if isinstance(ts, (int, float)):
                    ts = datetime.fromtimestamp(ts).isoformat()
                turns.append({"role": role, "content": content.strip(), "timestamp": str(ts)})
        else:
            # Simpler format: list of messages
            messages = conv.get("messages", [])
            for msg in messages:
                if not isinstance(msg, dict):
                    continue
                content_raw = msg.get("content", msg.get("text", "")) or ""
                if isinstance(content_raw, dict):
                    content = " ".join(str(p) for p in content_raw.get("parts", []))
                else:
                    content = str(content_raw)
                if not content or not content.strip():
                    continue
                role = msg.get("role") or (msg.get("author") or {}).get("role", "user")
                ts = msg.get("timestamp", msg.get("create_time", ""))
                turns.append({"role": role, "content": content.strip(), "timestamp": str(ts)})
    return turns


def _parse_markdown(text: str) -> list[dict]:
    """Parse Markdown/plain text → [{role, content, timestamp}, ...]"""
    # Try to detect conversation patterns
    lines = text.split("\n")
    turns = []
    current_role = "user"
    current_content: list[str] = []

    for line in lines:
        stripped = line.strip()
        # Detect role switches
        if stripped.lower().startswith(("human:", "user:", "你:", "我:")):
            if current_content:
                turns.append({"role": current_role, "content": "\n".join(current_content).strip(), "timestamp": ""})
            current_role = "user"
            content_after = stripped.split(":", 1)[1].strip() if ":" in stripped else ""
            current_content = [content_after] if content_after else []
        elif stripped.lower().startswith(("assistant:", "claude:", "ai:", "gpt:", "bot:", "deepseek:")):
            if current_content:
                turns.append({"role": current_role, "content": "\n".join(current_content).strip(), "timestamp": ""})
            current_role = "assistant"
            content_after = stripped.split(":", 1)[1].strip() if ":" in stripped else ""
            current_content = [content_after] if content_after else []
        else:
            current_content.append(line)

    if current_content:
        content = "\n".join(current_content).strip()
        if content:
            turns.append({"role": current_role, "content": content, "timestamp": ""})

    # If no role patterns detected, treat entire text as one big chunk
    if not turns:
        turns = [{"role": "user", "content": text.strip(), "timestamp": ""}]

    return turns


def detect_and_parse(raw_content: str, filename: str = "") -> list[dict]:
    """
    Auto-detect format and parse to normalized turns.
    自动检测格式并解析为标准化的对话轮次。
    """
    ext = Path(filename).suffix.lower() if filename else ""

    # Try JSON first
    if ext in (".json", "") or raw_content.strip().startswith(("{", "[")):
        try:
            data = json.loads(raw_content)
            # Detect Claude vs ChatGPT format
            if isinstance(data, list):
                sample = data[0] if data else {}
            else:
                sample = data

            if isinstance(sample, dict):
                if "chat_messages" in sample:
                    return _parse_claude_json(data)
                if "mapping" in sample:
                    return _parse_chatgpt_json(data)
                if "messages" in sample:
                    # Could be either — try ChatGPT first, fall back to Claude
                    msgs = sample["messages"]
                    if msgs and isinstance(msgs[0], dict) and "content" in msgs[0]:
                        if isinstance(msgs[0]["content"], dict):
                            return _parse_chatgpt_json(data)
                    return _parse_claude_json(data)
                # Single conversation object with role/content messages
                if "role" in sample and "content" in sample:
                    return _parse_claude_json(data)
        except (json.JSONDecodeError, KeyError, IndexError, AttributeError, TypeError):
            pass

    # Fall back to markdown/text
    return _parse_markdown(raw_content)


# ============================================================
# Chunking — split turns into ~10k token windows
# 分窗 — 按对话轮次边界切为 ~10k token 窗口
# ============================================================

def chunk_turns(turns: list[dict], target_tokens: int = _CHUNK_TARGET_TOKENS, human_label: str = "用户") -> list[dict]:
    """
    Group conversation turns into chunks of ~target_tokens.
    Returns list of {content, timestamp_start, timestamp_end, turn_count}.
    按对话轮次边界将对话分为 ~target_tokens 大小的窗口。
    human_label：对话中「用户」那一侧的称呼，默认「用户」，可传入 config["human"] 使内容更个人化。
    """
    chunks: list[dict] = []
    current_lines: list[str] = []
    current_tokens = 0
    first_ts = ""
    last_ts = ""
    turn_count = 0

    for turn in turns:
        role_label = human_label if turn["role"] in ("user", "human") else "AI"
        line = f"[{role_label}] {turn['content']}"
        line_tokens = count_tokens_approx(line)

        # If single turn exceeds target, split it
        if line_tokens > target_tokens * _CHUNK_OVERSIZE_RATIO:
            # Flush current
            if current_lines:
                chunks.append({
                    "content": "\n".join(current_lines),
                    "timestamp_start": first_ts,
                    "timestamp_end": last_ts,
                    "turn_count": turn_count,
                })
                current_lines = []
                current_tokens = 0
                turn_count = 0
                first_ts = ""

            # Add oversized turn as its own chunk
            chunks.append({
                "content": line,
                "timestamp_start": turn.get("timestamp", ""),
                "timestamp_end": turn.get("timestamp", ""),
                "turn_count": 1,
            })
            continue

        if current_tokens + line_tokens > target_tokens and current_lines:
            chunks.append({
                "content": "\n".join(current_lines),
                "timestamp_start": first_ts,
                "timestamp_end": last_ts,
                "turn_count": turn_count,
            })
            current_lines = []
            current_tokens = 0
            turn_count = 0
            first_ts = ""

        if not first_ts:
            first_ts = turn.get("timestamp", "")
        last_ts = turn.get("timestamp", "")
        current_lines.append(line)
        current_tokens += line_tokens
        turn_count += 1

    if current_lines:
        chunks.append({
            "content": "\n".join(current_lines),
            "timestamp_start": first_ts,
            "timestamp_end": last_ts,
            "turn_count": turn_count,
        })

    return chunks


def _detect_preview_format(raw_content: str, filename: str, warnings: list[str]) -> str:
    ext = Path(filename).suffix.lower() if filename else ""
    stripped = raw_content.strip()

    if ext == ".md":
        return "markdown"
    if ext in (".txt", ".jsonl"):
        return "text"

    if ext == ".json" or stripped.startswith(("{", "[")):
        try:
            data = json.loads(stripped)
            sample = data[0] if isinstance(data, list) and data else data
            if isinstance(sample, dict):
                if "chat_messages" in sample:
                    return "claude_json"
                if "mapping" in sample:
                    return "chatgpt_json"
                if "messages" in sample:
                    return "chat_json"
                if "role" in sample and "content" in sample:
                    return "chat_json"
            return "json"
        except (json.JSONDecodeError, TypeError, IndexError):
            warnings.append("JSON 解析失败，已按纯文本继续预检")
            return "text"

    return "markdown" if "\n" in raw_content else "text"


def preview_import(raw_content: str, filename: str = "", human_label: str = "用户") -> dict[str, Any]:
    """Return a local-only preview of an import file without mutating state."""
    warnings: list[str] = []
    if not raw_content or not raw_content.strip():
        return {
            "ok": False,
            "error": "Empty file",
            "detected_format": "",
            "turns_count": 0,
            "chunks_count": 0,
            "estimated_api_calls": 0,
            "warnings": ["文件为空"],
        }

    detected_format = _detect_preview_format(raw_content, filename, warnings)
    turns = detect_and_parse(raw_content, filename)
    if not turns:
        return {
            "ok": False,
            "error": "No conversation turns found",
            "detected_format": detected_format,
            "turns_count": 0,
            "chunks_count": 0,
            "estimated_api_calls": 0,
            "warnings": warnings,
        }

    chunks = chunk_turns(turns, human_label=human_label)
    if not chunks:
        return {
            "ok": False,
            "error": "No processable chunks after splitting",
            "detected_format": detected_format,
            "turns_count": len(turns),
            "chunks_count": 0,
            "estimated_api_calls": 0,
            "warnings": warnings,
        }

    token_estimate = sum(count_tokens_approx(chunk.get("content", "")) for chunk in chunks)
    first_preview = chunks[0].get("content", "")[:600]
    return {
        "ok": True,
        "detected_format": detected_format,
        "turns_count": len(turns),
        "chunks_count": len(chunks),
        "estimated_api_calls": len(chunks),
        "estimated_tokens": token_estimate,
        "warnings": warnings,
        "first_chunk_preview": first_preview,
        "sample_turns": [
            {
                "role": str(turn.get("role", "")),
                "content": str(turn.get("content", ""))[:160],
                "timestamp": str(turn.get("timestamp", "")),
            }
            for turn in turns[:3]
        ],
    }


# ============================================================
# Import State — persistent progress tracking
# 导入状态 — 持久化进度追踪
# ============================================================

class ImportState:
    """Manages import progress with file-based persistence."""

    def __init__(self, state_dir: str):
        self.state_file = os.path.join(state_dir, "import_state.json")
        self.data: dict[str, Any] = {
            "source_file": "",
            "source_hash": "",
            "total_chunks": 0,
            "processed": 0,
            "api_calls": 0,
            "memories_created": 0,
            "memories_merged": 0,
            "memories_raw": 0,
            "errors": [],
            "status": "idle",  # idle | running | paused | completed | error
            "started_at": "",
            "updated_at": "",
        }

    def load(self) -> bool:
        """Load state from file. Returns True if state exists."""
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                self.data.update(saved)
                return True
            except (json.JSONDecodeError, OSError):
                return False
        return False

    def save(self):
        """Persist state to file."""
        self.data["updated_at"] = now_iso()
        os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
        tmp = self.state_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.state_file)

    def reset(self, source_file: str, source_hash: str, total_chunks: int):
        """Reset state for a new import."""
        self.data = {
            "source_file": source_file,
            "source_hash": source_hash,
            "total_chunks": total_chunks,
            "processed": 0,
            "api_calls": 0,
            "memories_created": 0,
            "memories_merged": 0,
            "memories_raw": 0,
            "errors": [],
            "status": "running",
            "started_at": now_iso(),
            "updated_at": now_iso(),
        }

    @property
    def can_resume(self) -> bool:
        return self.data["status"] in ("paused", "running") and self.data["processed"] < self.data["total_chunks"]

    def to_dict(self) -> dict:
        return dict(self.data)


# ============================================================
# Import extraction prompt
# 导入提取提示词
# ============================================================

IMPORT_EXTRACT_PROMPT = """你是一个对话记忆提取专家。从以下对话片段中提取值得长期记住的信息。

提取规则：
1. 提取用户的事实、偏好、习惯、重要事件、情感时刻
2. 同一话题的零散信息整合为一条记忆
3. 过滤掉纯技术调试输出、代码块、重复问答、无意义寒暄
4. 如果对话中有特殊暗号、仪式性行为、关键承诺等，标记 preserve_raw=true
5. 如果内容是用户和我之间的习惯性互动模式（例如打招呼方式、告别习惯），标记 is_pattern=true
6. 每条记忆不少于30字
7. 总条目数控制在 0~5 个（没有值得记的就返回空数组）
8. 在 content 中对人名、地名、专有名词用 [[双链]] 标记

输出格式（纯 JSON 数组，无其他内容）：
[
  {
    "name": "条目标题（10字以内）",
    "content": "整理后的内容",
    "domain": ["主题域1"],
    "valence": 0.7,
    "arousal": 0.4,
    "tags": ["核心词1", "核心词2", "扩展词1"],
    "importance": 5,
    "preserve_raw": false,
    "is_pattern": false
  }
]

主题域可选（选 1~2 个）：
  日常: ["饮食", "穿搭", "出行", "居家", "购物"]
  人际: ["家庭", "恋爱", "友谊", "社交"]
  成长: ["工作", "学习", "考试", "求职"]
  身心: ["健康", "心理", "睡眠", "运动"]
  兴趣: ["游戏", "影视", "音乐", "阅读", "创作", "手工"]
  数字: ["编程", "AI", "硬件", "网络"]
  事务: ["财务", "计划", "待办"]
  内心: ["情绪", "回忆", "梦境", "自省"]

importance: 1-10
valence: 0~1（0=消极, 0.5=中性, 1=积极）
arousal: 0~1（0=平静, 0.5=普通, 1=激动）
preserve_raw: true = 特殊情境/暗号/仪式，保留原文不摘要
is_pattern: true = 反复出现的习惯性行为模式"""


# ============================================================
# Import Engine — core processing logic
# 导入引擎 — 核心处理逻辑
# ============================================================

class ImportEngine:
    """
    Processes conversation history files into OB memory buckets.
    将对话历史文件处理为 OB 记忆桶。
    """

    def __init__(self, config: dict, bucket_mgr, dehydrator, embedding_engine=None):
        self.config = config
        self.bucket_mgr = bucket_mgr
        self.dehydrator = dehydrator
        self.embedding_engine = embedding_engine
        self.state = ImportState(config["buckets_dir"])
        self._paused = False
        self._running = False
        self._chunks: list[dict] = []

    @property
    def is_running(self) -> bool:
        return self._running

    def pause(self):
        """Request pause — will stop after current chunk finishes."""
        self._paused = True

    def get_status(self) -> dict:
        """Get current import status."""
        return self.state.to_dict()

    async def start(
        self,
        raw_content: str,
        filename: str = "",
        preserve_raw: bool = False,
        resume: bool = False,
    ) -> dict:
        """
        Start or resume an import.
        开始或恢复导入。
        """
        if self._running:
            return {"error": "Import already running"}

        # 预检：LLM API 必须可用，否则所有 chunk 都会静默失败
        if not self.dehydrator.api_available:
            return {"error": "LLM API 未配置或不可用，导入需要 OMBRE_COMPRESS_API_KEY。请检查 config.yaml 或环境变量。"}

        self._running = True
        self._paused = False

        try:
            source_hash = hashlib.sha256(raw_content.encode()).hexdigest()[:_STATE_HASH_HEX]

            # Check for resume
            if resume and self.state.load() and self.state.can_resume:
                if self.state.data["source_hash"] == source_hash:
                    logger.info(
                        f"Resuming import from chunk "
                        f"{self.state.data['processed']}/{self.state.data['total_chunks']}"
                    )
                    # Re-parse and re-chunk to get the same chunks
                    turns = detect_and_parse(raw_content, filename)
                    _human = self.config.get("human", "用户")
                    self._chunks = chunk_turns(turns, human_label=_human)
                    self.state.data["status"] = "running"
                    self.state.save()
                    return await self._process_chunks(preserve_raw)
                else:
                    logger.warning("Source file changed, starting fresh import")

            # Fresh import
            turns = detect_and_parse(raw_content, filename)
            if not turns:
                self._running = False
                return {"error": "No conversation turns found in file"}

            _human = self.config.get("human", "用户")
            self._chunks = chunk_turns(turns, human_label=_human)
            if not self._chunks:
                self._running = False
                return {"error": "No processable chunks after splitting"}

            self.state.reset(filename, source_hash, len(self._chunks))
            self.state.save()

            logger.info(f"Starting import: {len(turns)} turns → {len(self._chunks)} chunks")
            return await self._process_chunks(preserve_raw)

        except Exception as e:
            self.state.data["status"] = "error"
            self.state.data["errors"].append(str(e))
            self.state.save()
            self._running = False
            raise

    async def _process_chunks(self, preserve_raw: bool) -> dict:
        """Process chunks from current position."""
        start_idx = self.state.data["processed"]

        for i in range(start_idx, len(self._chunks)):
            if self._paused:
                self.state.data["status"] = "paused"
                self.state.save()
                self._running = False
                logger.info(f"Import paused at chunk {i}/{len(self._chunks)}")
                return self.state.to_dict()

            chunk = self._chunks[i]
            try:
                await self._process_single_chunk(chunk, preserve_raw)
            except Exception as e:
                err_msg = f"Chunk {i}: {str(e)[:_CHUNK_ERR_PREVIEW]}"
                logger.warning(f"Import chunk error: {err_msg}")
                if len(self.state.data["errors"]) < _STATE_ERR_LOG_MAX:
                    self.state.data["errors"].append(err_msg)

            self.state.data["processed"] = i + 1
            # Save progress every chunk
            self.state.save()

        self.state.data["status"] = "completed"
        self.state.save()
        self._running = False
        logger.info(
            f"Import completed: {self.state.data['memories_created']} created, "
            f"{self.state.data['memories_merged']} merged"
        )
        return self.state.to_dict()

    async def _process_single_chunk(self, chunk: dict, preserve_raw: bool):
        """Extract memories from a single chunk and store them."""
        content = chunk["content"]
        if not content.strip():
            return

        # --- LLM extraction ---
        try:
            items = await self._extract_memories(content)
            self.state.data["api_calls"] += 1
        except Exception as e:
            err_msg = f"LLM extraction failed: {e}"
            logger.warning(err_msg)
            self.state.data["api_calls"] += 1
            # 把 LLM 失败原因写入 state.errors，让 /api/import/status 可见
            if len(self.state.data["errors"]) < _STATE_ERR_LOG_MAX:
                self.state.data["errors"].append(err_msg)
            return

        if not items:
            return

        # --- Store each extracted memory ---
        for item in items:
            try:
                should_preserve = preserve_raw or item.get("preserve_raw", False)

                if should_preserve:
                    # Raw mode: store original content without summarization
                    await self.bucket_mgr.create(
                        content=item["content"],
                        tags=item.get("tags", []),
                        importance=item.get("importance", _DEFAULT_IMPORTANCE),
                        domain=item.get("domain", ["未分类"]),
                        valence=item.get("valence", _DEFAULT_VALENCE),
                        arousal=item.get("arousal", _DEFAULT_AROUSAL),
                        name=item.get("name"),
                    )
                    self.state.data["memories_raw"] += 1
                    self.state.data["memories_created"] += 1
                else:
                    # Normal mode: go through merge-or-create pipeline
                    is_merged = await self._merge_or_create_item(item)
                    if is_merged:
                        self.state.data["memories_merged"] += 1
                    else:
                        self.state.data["memories_created"] += 1

                # Patch timestamp if available
                if chunk.get("timestamp_start"):
                    # We don't have update support for created, so skip
                    pass

            except Exception as e:
                logger.warning(f"Failed to store memory: {item.get('name', '?')}: {e}")

    async def _extract_memories(self, chunk_content: str) -> list[dict]:
        """Use LLM to extract memories from a conversation chunk."""
        if not self.dehydrator.api_available:
            raise RuntimeError("API not available")

        # 用 human 配置替换 prompt 里的「用户」称呼，让 LLM 输出更个人化。
        _human = self.config.get("human", "用户")
        prompt = IMPORT_EXTRACT_PROMPT.replace("用户", _human) if _human != "用户" else IMPORT_EXTRACT_PROMPT

        raw = await self.dehydrator._chat(
            prompt,
            chunk_content[:_EXTRACT_INPUT_LIMIT],
            max_tokens=_EXTRACT_MAX_TOKENS,
            temperature=_EXTRACT_TEMPERATURE,
        )

        if not raw.strip():
            return []

        return self._parse_extraction(raw)

    @staticmethod
    def _parse_extraction(raw: str) -> list[dict]:
        """Parse and validate LLM extraction result."""
        try:
            cleaned = _strip_md_fence(raw)
            items = json.loads(cleaned)
        except (json.JSONDecodeError, IndexError, ValueError):
            logger.warning(f"Import extraction JSON parse failed: {raw[:_PARSE_ERR_PREVIEW]}")
            return []

        if not isinstance(items, list):
            return []

        validated = []
        for item in items:
            if not isinstance(item, dict) or not item.get("content"):
                continue
            importance = _clamp_importance(item)
            valence, arousal = _clamp_va(item)

            validated.append({
                "name": str(item.get("name", ""))[:_NAME_MAX_CHARS],
                "content": str(item["content"]),
                "domain": item.get("domain", ["未分类"])[:_DOMAIN_MAX],
                "valence": valence,
                "arousal": arousal,
                "tags": [str(t) for t in item.get("tags", [])][:_TAGS_MAX],
                "importance": importance,
                "preserve_raw": parse_bool(
                    item.get("preserve_raw", False), default=False
                ),
                "is_pattern": parse_bool(
                    item.get("is_pattern", False), default=False
                ),
            })

        return validated

    async def _merge_or_create_item(self, item: dict) -> bool:
        """Try to merge with existing bucket, or create new. Returns is_merged."""
        content = item["content"]
        domain = item.get("domain", ["未分类"])
        tags = item.get("tags", [])
        importance = item.get("importance", _DEFAULT_IMPORTANCE)
        valence = item.get("valence", _DEFAULT_VALENCE)
        arousal = item.get("arousal", _DEFAULT_AROUSAL)
        name = item.get("name", "")

        try:
            existing = await self.bucket_mgr.search(content, limit=1, domain_filter=domain or None)
        except Exception as _search_exc:
            logger.warning(
                f"[import] Duplicate search failed, skipping merge check: "
                f"{type(_search_exc).__name__}: {_search_exc}"
            )
            existing = []

        merge_threshold = self.config.get("merge_threshold") or _DEFAULT_MERGE_THRESHOLD

        if existing and existing[0].get("score", 0) > merge_threshold:
            bucket = existing[0]
            if not (bucket["metadata"].get("pinned") or bucket["metadata"].get("protected")):
                try:
                    merged = await self.dehydrator.merge(bucket["content"], content)
                    self.state.data["api_calls"] += 1
                    old_v = bucket["metadata"].get("valence") or _DEFAULT_VALENCE
                    old_a = bucket["metadata"].get("arousal") or _DEFAULT_AROUSAL
                    await self.bucket_mgr.update(
                        bucket["id"],
                        content=merged,
                        tags=list(set((bucket["metadata"].get("tags") or []) + tags)),
                        importance=max(bucket["metadata"].get("importance") or _DEFAULT_IMPORTANCE, importance),
                        domain=list(set((bucket["metadata"].get("domain") or []) + domain)),
                        valence=round((old_v + valence) / 2, 2),
                        arousal=round((old_a + arousal) / 2, 2),
                    )
                    return True
                except Exception as e:
                    logger.warning(f"Merge failed during import: {e}")
                    self.state.data["api_calls"] += 1

        # Create new
        await self.bucket_mgr.create(
            content=content,
            tags=tags,
            importance=importance,
            domain=domain,
            valence=valence,
            arousal=arousal,
            name=name or None,
        )
        return False

    async def detect_patterns(self) -> list[dict]:
        """
        Post-import: detect high-frequency patterns via embedding clustering.
        导入后：通过 embedding 聚类检测高频模式。
        Returns list of {pattern_content, count, bucket_ids, suggested_action}.
        """
        if not self.embedding_engine:
            return []

        all_buckets = await self.bucket_mgr.list_all(include_archive=False)
        dynamic_buckets = [
            b for b in all_buckets
            if b["metadata"].get("type") == "dynamic"
            and not b["metadata"].get("pinned")
            and not b["metadata"].get("resolved")
        ]

        if len(dynamic_buckets) < _PATTERN_MIN_DYNAMIC_BUCKETS:
            return []

        # Get embeddings
        embeddings = {}
        for b in dynamic_buckets:
            emb = await self.embedding_engine.get_embedding(b["id"])
            if emb is not None:
                embeddings[b["id"]] = emb

        if len(embeddings) < _PATTERN_MIN_DYNAMIC_BUCKETS:
            return []

        # Find clusters: group by pairwise similarity > 0.7
        import numpy as np
        ids = list(embeddings.keys())
        clusters: dict[str, list[str]] = {}
        visited = set()

        for i, id_a in enumerate(ids):
            if id_a in visited:
                continue
            cluster = [id_a]
            visited.add(id_a)
            emb_a = np.array(embeddings[id_a])
            norm_a = np.linalg.norm(emb_a)
            if norm_a == 0:
                continue

            for j in range(i + 1, len(ids)):
                id_b = ids[j]
                if id_b in visited:
                    continue
                emb_b = np.array(embeddings[id_b])
                norm_b = np.linalg.norm(emb_b)
                if norm_b == 0:
                    continue
                sim = float(np.dot(emb_a, emb_b) / (norm_a * norm_b))
                if sim > _PATTERN_SIMILARITY_THRESHOLD:
                    cluster.append(id_b)
                    visited.add(id_b)

            if len(cluster) >= _PATTERN_MIN_CLUSTER_SIZE:
                clusters[id_a] = cluster

        # Format results
        patterns = []
        for lead_id, cluster_ids in clusters.items():
            lead_bucket = next((b for b in dynamic_buckets if b["id"] == lead_id), None)
            if not lead_bucket:
                continue
            patterns.append({
                "pattern_content": lead_bucket["content"][:_PATTERN_CONTENT_PREVIEW],
                "pattern_name": lead_bucket["metadata"].get("name", lead_id),
                "count": len(cluster_ids),
                "bucket_ids": cluster_ids,
                "suggested_action": "pin" if len(cluster_ids) >= _PATTERN_PIN_SUGGEST_THRESHOLD else "review",
            })

        patterns.sort(key=lambda p: p["count"], reverse=True)
        return patterns[:_PATTERN_RESULT_LIMIT]
