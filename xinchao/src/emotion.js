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
    ensureEmotionJournal(state);
    return state.emotion;
  }
  current.valence = round4(current.valence);
  current.arousal = round4(current.arousal);
  current.label = emotionLabel(current.valence, current.arousal);
  current.lastCause = current.lastCause ? String(current.lastCause).slice(0, 80) : null;
  current.lastCauseAt = current.lastCauseAt ?? null;
  current.updatedAt = current.updatedAt ?? iso(now);
  ensureEmotionJournal(state);
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
  if (changed) recordEmotionSample(state, now, { cause });
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
  const changed = emotion.valence !== before.valence || emotion.arousal !== before.arousal || emotion.label !== before.label;
  const sampled = recordEmotionSample(state, options.now ?? new Date(), { timeZone: options.timeZone }).recorded;
  return { changed: changed || sampled, emotion, target };
}

export function emotionSummary(state, now = new Date()) {
  const emotion = state?.emotion && typeof state.emotion === 'object' ? state.emotion : newEmotion();
  return {
    trend: emotionTrend(state, now, 24),
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

// ── 情绪 → 记忆（3.3 第二步）────────────────────────────────────────
// OB 的 breath 接受 valence/arousal 作为共振坐标，hold 接受它们作为显式情感标签。
// 心潮自己去 OB 拉材料时把此刻情绪带上；顾川经心潮网关调 breath/hold 而没自己给坐标时，
// 也替他补上。grow 没有这个参数，不碰。
//
// hold 只在"明显有情绪"时才盖章：平静状态下存一条难过的往事，OB 自己按内容打的标更准；
// 情绪明显偏离中性时，他此刻的心情大概率就是这条记忆的心情。

export const STAMP_MIN_DEVIATION = 0.15;   // hold 盖章门槛：|valence-0.5| 或 arousal 偏离基线

export function emotionCoords(state) {
  const summary = emotionSummary(state);
  return { valence: summary.valence, arousal: summary.arousal };
}

function hasOwnCoord(value) {
  const n = Number(value);
  return Number.isFinite(n) && n >= 0 && n <= 1;
}

// 返回补好坐标的 args（新对象），或原 args（没补）。
export function stampEmotionArgs(name, args, state, options = {}) {
  const tool = String(name ?? '');
  const input = args && typeof args === 'object' ? args : {};
  if (tool !== 'breath' && tool !== 'hold') return { args: input, stamped: false };
  if (hasOwnCoord(input.valence) || hasOwnCoord(input.arousal)) return { args: input, stamped: false };
  const coords = emotionCoords(state);
  if (tool === 'hold') {
    const minDeviation = Number(options.minDeviation ?? STAMP_MIN_DEVIATION);
    const deviation = Math.max(Math.abs(coords.valence - 0.5), Math.abs(coords.arousal - EMOTION_BASELINE.arousal));
    if (deviation < minDeviation) return { args: input, stamped: false };
  }
  return { args: { ...input, valence: coords.valence, arousal: coords.arousal }, stamped: true, coords };
}

// ── 情绪 → 驱力（3.3 第四步）────────────────────────────────────────
// 情绪不直接往驱力数值上加，只改"接下来自然长多快"——和 3.1 的 anger/grieve 耦合同一条路，
// 所以结算多频繁都不会自激。难受的时候更惦记、更黏；开心的时候更想分享、更好奇；
// 亢奋时不无聊也静不下来沉淀；倦了什么都慢一点（疲劳那边已经在压，这里不再叠）。
//
// 系数含义：rate *= clamp(1 + valenceSlope·dv + arousalSlope·da, 0.4, 1.8)，
// dv = (valence-0.5)·2 ∈ [-1,1]，da = (arousal-基线)/0.7 ∈ [-1,1]。中性情绪时因子恒为 1，和没这层一样。
export const EMOTION_GROWTH_MODULATION = Object.freeze({
  monitor:    { valence: -0.35, arousal: +0.25 },
  crave:      { valence: -0.25, arousal: +0.10 },
  possess:    { valence: -0.15, arousal: +0.15 },
  share:      { valence: +0.35, arousal: +0.15 },
  curiosity:  { valence: +0.25, arousal: +0.20 },
  social:     { valence: +0.25, arousal: +0.10 },
  libido:     { valence: +0.20, arousal: +0.25 },
  boredom:    { valence: -0.10, arousal: -0.30 },
  reflection: { valence: -0.10, arousal: -0.25 },
  duty:       { valence: 0,     arousal: +0.10 },
});
const MODULATION_FLOOR = 0.4;
const MODULATION_CEIL = 1.8;

export function emotionGrowthFactor(driveKey, emotion) {
  const mod = EMOTION_GROWTH_MODULATION[driveKey];
  if (!mod || !emotion) return 1;
  const v = Number(emotion.valence);
  const a = Number(emotion.arousal);
  if (!Number.isFinite(v) || !Number.isFinite(a)) return 1;
  const dv = clamp((v - 0.5) * 2, -1, 1);
  const da = clamp((a - EMOTION_BASELINE.arousal) / 0.7, -1, 1);
  return Number(clamp(1 + mod.valence * dv + mod.arousal * da, MODULATION_FLOOR, MODULATION_CEIL).toFixed(4));
}

// ── 情绪日志（3.3 第五块，自我觉察的第一份原料）────────────────────────
// 当下值只回答"我现在怎样"，觉察需要的是"我这阵子怎样"。日志两层：
//   samples：逐条采样（结算时每 ≥2h 一条；事件脉冲时标签变了或隔 ≥30min 一条，带成因），最多保留 30 天/600 条；
//   days：按天（Asia/Shanghai）聚合的摘要——均值、最低愉悦、最高唤醒、各标签次数、各成因次数，保留 30 天。
// 不存正文，只存坐标、词和互动类型名。
const JOURNAL_MAX_SAMPLES = 600;
const JOURNAL_MAX_DAYS = 30;
const SAMPLE_SETTLE_GAP_MS = 2 * 3_600_000;
const SAMPLE_IMPULSE_GAP_MS = 30 * 60_000;

function dayKey(at, timeZone = 'Asia/Shanghai') {
  try {
    return new Intl.DateTimeFormat('en-CA', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(at));
  } catch {
    return iso(at).slice(0, 10);
  }
}

export function ensureEmotionJournal(state) {
  state.emotionJournal = Array.isArray(state.emotionJournal) ? state.emotionJournal.slice(-JOURNAL_MAX_SAMPLES) : [];
  state.emotionDays = state.emotionDays && typeof state.emotionDays === 'object' ? state.emotionDays : {};
  return state;
}

function pruneDays(days, now) {
  const keys = Object.keys(days).sort();
  const cutoff = dayKey(new Date(new Date(now).getTime() - JOURNAL_MAX_DAYS * 86_400_000));
  for (const key of keys) if (key < cutoff) delete days[key];
  return days;
}

export function recordEmotionSample(state, now = new Date(), options = {}) {
  ensureEmotionJournal(state);
  const emotion = ensureEmotion(state, now);
  const cause = options.cause ? String(options.cause).slice(0, 80) : null;
  const last = state.emotionJournal.at(-1);
  const nowMs = new Date(now).getTime();
  const gap = last ? nowMs - Date.parse(last.at) : Infinity;
  const labelChanged = !last || last.label !== emotion.label;
  const minGap = cause ? SAMPLE_IMPULSE_GAP_MS : SAMPLE_SETTLE_GAP_MS;
  if (!options.force && !labelChanged && gap < minGap) return { recorded: false };
  const drives = state.drives && typeof state.drives === 'object' ? Object.entries(state.drives) : [];
  const top = drives.length ? drives.sort((a, b) => Number(b[1]) - Number(a[1]))[0][0] : null;
  const sample = { at: iso(now), valence: emotion.valence, arousal: emotion.arousal, label: emotion.label, cause, top };
  state.emotionJournal.push(sample);
  state.emotionJournal = state.emotionJournal.slice(-JOURNAL_MAX_SAMPLES);
  const key = dayKey(now, options.timeZone);
  const day = state.emotionDays[key] ?? { samples: 0, meanValence: 0, meanArousal: 0, minValence: 1, maxArousal: 0, labels: {}, causes: {} };
  day.meanValence = round4((day.meanValence * day.samples + emotion.valence) / (day.samples + 1));
  day.meanArousal = round4((day.meanArousal * day.samples + emotion.arousal) / (day.samples + 1));
  day.minValence = Math.min(day.minValence, emotion.valence);
  day.maxArousal = Math.max(day.maxArousal, emotion.arousal);
  day.samples += 1;
  day.labels[emotion.label] = (day.labels[emotion.label] ?? 0) + 1;
  if (cause) day.causes[cause] = (day.causes[cause] ?? 0) + 1;
  state.emotionDays[key] = day;
  pruneDays(state.emotionDays, now);
  return { recorded: true, sample };
}

// 近 N 小时的走势：去重后的标签序列 + 成因计数。给信封和觉察用。
export function emotionTrend(state, now = new Date(), hours = 24) {
  const since = new Date(now).getTime() - hours * 3_600_000;
  const samples = (state?.emotionJournal ?? []).filter((item) => Date.parse(item.at) >= since);
  const labels = [];
  const causes = {};
  let minValence = 1;
  let maxArousal = 0;
  for (const item of samples) {
    if (labels.at(-1) !== item.label) labels.push(item.label);
    if (item.cause) causes[item.cause] = (causes[item.cause] ?? 0) + 1;
    minValence = Math.min(minValence, item.valence);
    maxArousal = Math.max(maxArousal, item.arousal);
  }
  return { hours, samples: samples.length, labels, causes, minValence: samples.length ? round4(minValence) : null, maxArousal: samples.length ? round4(maxArousal) : null };
}

export function renderEmotionTrend(trend) {
  if (!trend || trend.samples < 2 || trend.labels.length < 2) return '';
  const causes = Object.entries(trend.causes).sort((a, b) => b[1] - a[1]).slice(0, 3).map(([k, n]) => `${k}×${n}`).join('，');
  return `近${trend.hours}小时情绪走过：${trend.labels.join('→')}${causes ? `（${causes}）` : ''}`;
}
