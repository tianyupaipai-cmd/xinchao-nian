const FLASH_DECAY       = 0.82;
const OBSESSION_GROWTH  = 1.10;
const PROMOTE_THRESHOLD = 0.50;
const PROMOTE_MIN_AGE   = 3;
const FEEDBACK_AMOUNT   = 0.18;
const FEEDBACK_CEIL     = 0.85;
const MAX_FEEDBACKS     = 3;
const MAX_FLASH         = 8;
const MAX_OBSESSIONS    = 3;

export function newThoughtPool() {
  return { flash: [], obsessions: [] };
}

export function tickThoughtPool(pool) {
  pool.flash = pool.flash
    .map((t) => ({ ...t, intensity: t.intensity * FLASH_DECAY, age: t.age + 1 }))
    .filter((t) => t.intensity > 0.05);

  const promoted = [];
  pool.flash = pool.flash.filter((t) => {
    if (t.intensity >= PROMOTE_THRESHOLD && t.age >= PROMOTE_MIN_AGE && pool.obsessions.length + promoted.length < MAX_OBSESSIONS) {
      promoted.push({
        key: t.key,
        text: t.text,
        intensity: t.intensity,
        feedbacks: 0,
        ombreBucketId: t.ombreBucketId ?? null,
        sourceOmbreBucketIds: Array.isArray(t.sourceOmbreBucketIds) ? [...t.sourceOmbreBucketIds] : [],
      });
      return false;
    }
    return true;
  });
  pool.obsessions.push(...promoted);

  const feedbacks = {};
  pool.obsessions = pool.obsessions
    .map((o) => {
      const next = { ...o, intensity: Math.min(1, o.intensity * OBSESSION_GROWTH) };
      if (next.intensity > FEEDBACK_CEIL && next.feedbacks < MAX_FEEDBACKS) {
        feedbacks[next.key] = (feedbacks[next.key] ?? 0) + FEEDBACK_AMOUNT;
        next.feedbacks += 1;
      }
      return next;
    })
    .filter((o) => o.feedbacks < MAX_FEEDBACKS);

  return feedbacks;
}

function normalizeMemoryRefs(metadata = {}) {
  const ids = Array.isArray(metadata.sourceOmbreBucketIds)
    ? metadata.sourceOmbreBucketIds.map(String).map((id) => id.trim()).filter(Boolean)
    : [];
  const primary = String(metadata.ombreBucketId ?? ids[0] ?? '').trim() || null;
  return {
    ombreBucketId: primary,
    sourceOmbreBucketIds: [...new Set(primary ? [primary, ...ids] : ids)].slice(0, 8),
  };
}

export function addFlashThought(pool, key, text, intensity = 0.70, metadata = {}) {
  if (pool.flash.length >= MAX_FLASH) {
    pool.flash.sort((a, b) => a.intensity - b.intensity);
    pool.flash.shift();
  }
  pool.flash.push({
    key,
    text,
    intensity: Math.min(1, intensity),
    age: 0,
    ...normalizeMemoryRefs(metadata),
  });
}

export function obsessionBonus(pool, key) {
  const hit = (pool?.obsessions ?? []).find((o) => o.key === key);
  return hit ? hit.intensity * 0.15 : 0;
}

// 输出回流：他自己说出口的一次表达，回过头在思维池里给对应驱力留一道痕。
// 走这条通道而不是直接加驱力，是为了让"说了 → 想念涨"这件事天然收敛：
// 一次性的表达只会落一条会衰减的 flash，自己散掉；只有反复表达同一件事
// （同一 key 在还没衰减完时被再次强化）才累积到 PROMOTE_THRESHOLD 并熬过
// PROMOTE_MIN_AGE，升成 obsession —— 那时才会有界地把驱力顶上去几次然后退休。
// 执念本来就是这么形成的，所以不完全阻尼；上限由既有池机制（MAX_FEEDBACKS）
// 和输出本身的发送频率闸门共同兜底。
export function reinforceThought(pool, key, text, amount = 0.30, metadata = {}) {
  pool.flash ??= [];
  const step = Math.min(1, Math.max(0, Number(amount) || 0));
  const existing = pool.flash.find((t) => t.key === key);
  if (existing) {
    existing.intensity = Math.min(1, existing.intensity + step);
    if (text) existing.text = text;
    const refs = normalizeMemoryRefs(metadata);
    if (refs.ombreBucketId) existing.ombreBucketId = refs.ombreBucketId;
    existing.sourceOmbreBucketIds = [...new Set([
      ...(existing.sourceOmbreBucketIds ?? []),
      ...refs.sourceOmbreBucketIds,
    ])].slice(0, 8);
    return { key, intensity: Number(existing.intensity.toFixed(4)), seeded: false };
  }
  addFlashThought(pool, key, text, step, metadata);
  const created = pool.flash.find((t) => t.key === key);
  return { key, intensity: Number((created?.intensity ?? step).toFixed(4)), seeded: true };
}
