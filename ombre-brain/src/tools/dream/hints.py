"""
========================================
tools/dream/hints.py — dream 的连接提示与结晶提示
========================================

两个可选的引导句，写在 dream 输出末尾，帮模型「看见」它自己没注意
到的关联：

- 连接提示：在 recent 桶里找余弦相似度最高的一对（>0.5）→ 提示
  「这两个似乎有关联，不替你下结论，你自己想」
- 结晶提示：扫所有 feel，发现某条 feel 与 ≥2 条其它 feel 相似度
  >0.7 → 提示「你已经写过 N 条相似的 feel，可以考虑 hold(pinned=True)
  升级它」

关键行为：
- 都依赖 embedding_engine.enabled；未启用时返回空串
- 任意异常都吞掉，只 warning，不影响 dream 主流程

不做什么（边界）：
- 不写桶，不修改任何状态
- 不替模型决定，只给「不替你下结论」的提示

对外暴露：build_connection_hint(recent) / build_crystal_hint(all_buckets)
========================================
"""

from .. import _runtime as rt
from utils import strip_wikilinks


async def build_connection_hint(recent: list) -> str:
    if not (rt.embedding_engine and rt.embedding_engine.enabled and len(recent) >= 2):
        return ""
    try:
        best_pair = None
        best_sim = 0.0
        ids = [b["id"] for b in recent]
        names = {b["id"]: b["metadata"].get("name", b["id"]) for b in recent}
        embeddings: dict = {}
        for bid in ids:
            emb = await rt.embedding_engine.get_embedding(bid)
            if emb is not None:
                embeddings[bid] = emb
        for i, id_a in enumerate(ids):
            for id_b in ids[i + 1:]:
                if id_a in embeddings and id_b in embeddings:
                    sim = rt.embedding_engine._cosine_similarity(embeddings[id_a], embeddings[id_b])
                    if sim > best_sim:
                        best_sim = sim
                        best_pair = (id_a, id_b)
        if best_pair and best_sim > 0.5:
            return (
                f"\n💭 [{names[best_pair[0]]}] 和 [{names[best_pair[1]]}] "
                f"似乎有关联 (相似度:{best_sim:.2f})——不替你下结论，你自己想。\n"
            )
    except Exception as e:
        rt.logger.warning(f"Dream connection hint failed: {e}")
    return ""


async def build_crystal_hint(all_buckets: list) -> str:
    if not (rt.embedding_engine and rt.embedding_engine.enabled):
        return ""
    try:
        feels = [b for b in all_buckets if b["metadata"].get("type") == "feel"]
        if len(feels) < 3:
            return ""
        feel_embeddings: dict = {}
        for f in feels:
            emb = await rt.embedding_engine.get_embedding(f["id"])
            if emb is not None:
                feel_embeddings[f["id"]] = emb
        for fid, femb in feel_embeddings.items():
            similar_feels = []
            for oid, oemb in feel_embeddings.items():
                if oid != fid:
                    sim = rt.embedding_engine._cosine_similarity(femb, oemb)
                    if sim > 0.7:
                        similar_feels.append(oid)
            if len(similar_feels) >= 2:
                feel_bucket = next((f for f in feels if f["id"] == fid), None)
                if feel_bucket and not feel_bucket["metadata"].get("pinned"):
                    content_preview = strip_wikilinks(feel_bucket["content"][:80])
                    return (
                        f"\n🔮 你已经写过 {len(similar_feels)+1} 条相似的 feel "
                        f"（围绕「{content_preview}…」）。"
                        f"如果这已经是确信而不只是感受了，"
                        f"你可以用 hold(content=\"...\", pinned=True) 升级它。"
                        f"不急，你自己决定。\n"
                    )
    except Exception as e:
        rt.logger.warning(f"Dream crystallization hint failed: {e}")
    return ""
