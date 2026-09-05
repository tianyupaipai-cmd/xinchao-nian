// 情绪层（3.3 第一步）—— 独立于 12 维驱力的一层"此刻的心情"。
//
// 驱力回答"我想要什么"，情绪回答"我现在是什么状态"。两者分开存：驱力是欲望的压力，
// 慢慢涨、被满足才落；情绪是被事情砸出来的水花，有惯性，几个小时自己平回去。
//
// 坐标沿用 OB 记忆桶的约定：valence（愉悦，0 难受…1 舒服）、arousal（唤醒，0 倦…1 亢奋），
// 都是 0–1，0.5 居中。这样第二步往 breath 传情绪坐标时不用换算。
//
// 来源三路：
//   1. 互动事件（affection / conflict / loss …）打一次脉冲；
//   2. 会话短态的 tone（warm / guarded / tired …）把情绪往对应位置拉一点；
//   3. grieve / anger 两个驱力在结算时把"回落目标"往下拽——难过着的时候，平静不是平静。
// 情绪不直接改驱力（那是第四步的事），也不自激：每次结算只做指数回落，没有增长项。

const clamp = (value, min = 0, max = 1) => Math.max(min, Math.min(max, Number(value) || 0));
const round4 = (value) => Number(clamp(value).toFixed(4));
const iso = (value) => new Date(value).toISOString();

export const EMOTION_BASELINE = Object.freeze({ valence: 0.55, arousal: 0.30 });
// 半衰期（小时）：愉悦感散得慢，亢奋散得快；睡着了都散得更快。
export const VALENCE_HALF_LIFE_HOURS = 6;
export const AROUSAL_HALF_LIFE_HOURS = 3;
const SLEEP_DECAY_MUL = 2;
// 单次脉冲最多推多远；连续同向脉冲有惯性：离中性越远，再往同一边推越费劲。
const IMPULSE_CAP = 0.25;

export const INTERACTION_EMOTION = Object.freeze({
  companionship:  { valence: +0.06, arousal: +0.02 },
  affection:      { valence: +0.12, arousal: +0.08 },
  intimacy:       { valence: +0.15, arousal: +0.20 },
  sharing:        { valence: +0.08, arousal: +0.06 },
  discovery:      { valence: +0.05, arousal: +0.10 },
  task_progress:  { valence: +0.04, arousal: 0 },
  reflection:     { valence: 0,     arousal: -0.08 },
  conflict:       { valence: -0.18, arousal: +0.20 },
  loss:           { valence: -0.15, arousal: -0.05 },
  reconciliation: { valence: +0.14, arousal: -0.05 },
});

// 会话 tone → 情绪落点。neutral 不拉。
export const TONE_TARGET = Object.freeze({
  warm:       { valence: 0.70, arousal: 0.40 },
  playful:    { valence: 0.72, arousal: 0.55 },
  calm:       { valence: 0.62, arousal: 0.20 },
  focused:    { valence: 0.55, arousal: 0.45 },
  tired:      { valence: 0.45, arousal: 0.15 },
  guarded:    { valence: 0.40, arousal: 0.50 },
  conflicted: { valence: 0.35, arousal: 0.60 },
});
const TONE_BLEND = 0.15;

// 驱力对回落目标的拉扯：难过压愉悦，生气压愉悦、抬唤醒。只改目标，不改增长。
const DRIVE_PULL = Object.freeze({
  grieve: { valence: -0.35, arousal: -0.05 },
  anger:  { valence: -0.25, arousal: +0.30 },
});

export function newEmotion(now = new Date()) {
  return {
    valence: EMOTION_BASELINE.valence,
    arousal: EMOTION_BASELINE.arousal,
    label: emotionLabel(EMOTION_BASELINE.valence, EMOTION_BASELINE.arousal),
    updatedAt: iso(now),
    lastCause: null,
    lastCauseAt: null,
  };
}

export function ensureEmotion(state, now = new Date()) {
  const current = state.emotion && typeof state.emotion === 'object' ? state.emotion : null;
  if (!current || !Number.isFinite(Number(current.valence)) || !Number.isFinite(Number(current.arousal))) {
    state.emotion = newEmotion(now);
    return state.emotion;
  }
  current.valence = round4(current.valence);
  current.arousal = round4(current.arousal);
  current.label = emotionLabel(current.valence, current.arousal);
  current.lastCause = current.lastCause ? String(current.lastCause).slice(0, 80) : null;
  current.lastCauseAt = current.lastCauseAt ?? null;
  current.updatedAt = current.updatedAt ?? iso(now);
  return current;
}

// 二维落到一个词上。给上下文信封和 Dashboard 用；模型看词，不看数。
export function emotionLabel(valence, arousal) {
  const v = clamp(valence);
  const a = clamp(arousal);
  if (v >= 0.68 && a >= 0.50) return '雀跃';
  if (v >= 0.68) return '安心';
  if (v <= 0.38 && a >= 0.50) return '烦躁';
  if (v <= 0.38) return '低落';
  if (v >= 0.58 && a <= 0.22) return '松弛';
  if (a >= 0.62) return '紧绷';
  if (a <= 0.18) return '倦';
  return '平静';
}

// 目标点 = 中性基线 + 驱力拉扯。
export function emotionTarget(drives = {}) {
  let valence = EMOTION_BASELINE.valence;
  let arousal = EMOTION_BASELINE.arousal;
  for (const [key, pull] of Object.entries(DRIVE_PULL)) {
    const level = clamp(drives?.[key]);
    valence += pull.valence * level;
    arousal += pull.arousal * level;
  }
  return { valence: round4(valence), arousal: round4(arousal) };
}

// 一次脉冲：事件砸出来的水花。带惯性——已经很高兴时再高兴一点，比从低落爬上来推得少。
export function applyEmotionImpulse(state, impulse = {}, cause = '', now = new Date()) {
  const emotion = ensureEmotion(state, now);
  const dv = clamp(Number(impulse.valence) || 0, -IMPULSE_CAP, IMPULSE_CAP);
  const da = clamp(Number(impulse.arousal) || 0, -IMPULSE_CAP, IMPULSE_CAP);
  if (dv === 0 && da === 0) return { changed: false, emotion };
  const before = { valence: emotion.valence, arousal: emotion.arousal };
  // 惯性：往某个方向推时，按"那个方向还剩多少空间"折算。推向 1 时乘 (1-v)，推向 0 时乘 v。
  const inertia = (value, delta) => (delta > 0 ? delta * (1 - value) * 1.6 : delta * value * 1.6);
  emotion.valence = round4(emotion.valence + inertia(emotion.valence, dv));
  emotion.arousal = round4(emotion.arousal + inertia(emotion.arousal, da));
  emotion.label = emotionLabel(emotion.valence, emotion.arousal);
  emotion.updatedAt = iso(now);
  if (cause) {
    emotion.lastCause = String(cause).slice(0, 80);
    emotion.lastCauseAt = iso(now);
  }
  const changed = emotion.valence !== before.valence || emotion.arousal !== before.arousal;
  return { changed, emotion, applied: { valence: round4(emotion.valence - before.valence + 0.5) - 0.5, arousal: round4(emotion.arousal - before.arousal + 0.5) - 0.5 } };
}

// 会话 tone 的拉扯：不是脉冲，是往一个落点靠一小段。
export function blendEmotionTowardTone(state, tone, now = new Date(), weight = TONE_BLEND) {
  const target = TONE_TARGET[String(tone ?? '').toLowerCase()];
  if (!target) return { changed: false };
  const emotion = ensureEmotion(state, now);
  const before = { valence: emotion.valence, arousal: emotion.arousal };
  emotion.valence = round4(emotion.valence + (target.valence - emotion.valence) * weight);
  emotion.arousal = round4(emotion.arousal + (target.arousal - emotion.arousal) * weight);
  emotion.label = emotionLabel(emotion.valence, emotion.arousal);
  emotion.updatedAt = iso(now);
  return { changed: emotion.valence !== before.valence || emotion.arousal !== before.arousal, emotion };
}

// 时间结算：指数回落到目标点。没有增长项，所以结算多频繁都不会自激。
export function settleEmotion(state, elapsedHours = 0, options = {}) {
  const emotion = ensureEmotion(state, options.now ?? new Date());
  const hours = Math.max(0, Number(elapsedHours) || 0);
  const target = emotionTarget(options.drives ?? state.drives ?? {});
  const mul = options.sleeping ? SLEEP_DECAY_MUL : 1;
  const decay = (value, goal, halfLife) => goal + (value - goal) * Math.pow(0.5, (hours * mul) / halfLife);
  const before = { valence: emotion.valence, arousal: emotion.arousal, label: emotion.label };
  emotion.valence = round4(decay(emotion.valence, target.valence, VALENCE_HALF_LIFE_HOURS));
  emotion.arousal = round4(decay(emotion.arousal, target.arousal, AROUSAL_HALF_LIFE_HOURS));
  emotion.label = emotionLabel(emotion.valence, emotion.arousal);
  return {
    changed: emotion.valence !== before.valence || emotion.arousal !== before.arousal || emotion.label !== before.label,
    emotion,
    target,
  };
}

export function emotionSummary(state) {
  const emotion = state?.emotion && typeof state.emotion === 'object' ? state.emotion : newEmotion();
  return {
    valence: round4(emotion.valence),
    arousal: round4(emotion.arousal),
    label: emotionLabel(emotion.valence, emotion.arousal),
    updatedAt: emotion.updatedAt ?? null,
    lastCause: emotion.lastCause ?? null,
    lastCauseAt: emotion.lastCauseAt ?? null,
  };
}

// 给上下文信封的一行。模型看到的是词和成因，数值放括号里作参考。
export function renderEmotion(summary) {
  if (!summary) return '';
  const cause = summary.lastCause ? `，最近一次波动来自「${summary.lastCause}」` : '';
  return `此刻情绪：${summary.label}（愉悦=${summary.valence.toFixed(2)} 唤醒=${summary.arousal.toFixed(2)}）${cause}`;
}
