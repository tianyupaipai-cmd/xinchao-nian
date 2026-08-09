"""
bm25_index.py — BM25 稀疏检索，配合 jieba 中文分词。
给 bucket_manager.search() 提供 TF-IDF 加权的关键词召回（Dim 7）。

rank_bm25 / jieba 均为软依赖：未安装时所有方法静默 no-op，不影响其余检索维度。
BM25Index 由 BucketManager 持有，写操作后脏标记，search() 时懒重建。
"""
from __future__ import annotations

import logging

logger = logging.getLogger("ombre_brain.bm25")

try:
    from rank_bm25 import BM25Okapi as _BM25Okapi
    _BM25_AVAILABLE = True
except ImportError:
    _BM25Okapi = None  # type: ignore
    _BM25_AVAILABLE = False
    logger.info("[bm25] rank_bm25 未安装 — BM25 关键词检索已禁用（pip install rank-bm25 启用）")

try:
    import jieba as _jieba
    _jieba.setLogLevel(logging.WARNING)
    _JIEBA_AVAILABLE = True
except ImportError:
    _jieba = None  # type: ignore
    _JIEBA_AVAILABLE = False
    logger.info("[bm25] jieba 未安装 — 回退空格分词（pip install jieba 启用中文分词）")


def _tokenize(text: str) -> list[str]:
    """中文 jieba 分词 + 空格切割英文，小写，过滤空串。"""
    if not text:
        return []
    text = text.lower()
    if _JIEBA_AVAILABLE:
        tokens = list(_jieba.cut_for_search(text))
    else:
        tokens = text.split()
    return [t for t in tokens if t.strip()]


class BM25Index:
    """内存 BM25 倒排索引门面。

    lifecycle:
        build(buckets)  — 重建索引（BucketManager 在写操作后脏标记，search 时懒调用）
        score(query)    — 返回 {bucket_id: normalized_score}，分值 [0, 1]
    """

    def __init__(self):
        self._index = None          # BM25Okapi instance or None
        self._ids: list[str] = []

    @property
    def available(self) -> bool:
        return _BM25_AVAILABLE

    def build(self, buckets: list[dict]) -> None:
        """重建索引。文档 = name + content[:1200] + tags + domain 拼接后分词。"""
        if not _BM25_AVAILABLE:
            return
        corpus: list[list[str]] = []
        ids: list[str] = []
        for b in buckets:
            meta = b.get("metadata", {})
            text = " ".join([
                meta.get("name") or "",
                b.get("content", "")[:1200],
                " ".join(meta.get("tags", []) or []),
                " ".join(meta.get("domain", []) or []),
            ])
            tokens = _tokenize(text)
            if tokens:
                corpus.append(tokens)
                ids.append(b["id"])
        if corpus:
            self._index = _BM25Okapi(corpus)
        else:
            self._index = None
        self._ids = ids

    def score(self, query: str) -> dict[str, float]:
        """返回 {bucket_id: normalized_bm25_score}，最高分 = 1.0，无命中返回 {}。"""
        if not _BM25_AVAILABLE or self._index is None:
            return {}
        tokens = _tokenize(query)
        if not tokens:
            return {}
        raw = self._index.get_scores(tokens)  # numpy ndarray
        max_s = float(raw.max()) if raw.size > 0 else 0.0
        if max_s <= 0:
            return {}
        return {bid: float(s) / max_s for bid, s in zip(self._ids, raw) if s > 0}
