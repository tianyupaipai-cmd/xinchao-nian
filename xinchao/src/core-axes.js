// 驱力第 8 步（10-03）：花蕊里的三根慢轴。不是驱力，不叫醒他，变得慢，几天才回到底色。
//   · 安全感：怕不怕被丢下。偏爱长时间挂着、吵了没和好、被冷落会往下掉；被哄、被选、和好会慢慢回来。
//   · 自信：有没有底气。做成事、被夸、帮到人会变厚；自责、被说不满会变薄。
//   · 心境：这几天整体偏亮还是偏沉。不单独存，直接取情绪日志最近三天的平均愉悦。
// 影响：安全感低时难过更容易涨、情绪显示「不安」；自信低时「得意」亮不起来、自信高时自责沉得浅一点。
// 平时不显示，偏离底色明显（≥0.15）才在「此刻」里多一句。网页上画成花蕊的两圈环（外圈安全感、里圈自信，颜色是心境）。

const H = 3_600_000;
const iso = (d) => d.toISOString();
const clamp = (v, lo = 0.05, hi = 0.95) => Math.max(lo, Math.min(hi, Number(v) || 0));

export const AXES = Object.freeze({
  baseline: { security: 0.62, confidence: 0.6 },
  halfLifeHours: 72,          // 没事时回到底色的半衰期
  low: 0.35, high: 0.75, shownDelta: 0.15,
});

// 每种事件对两根轴的推动（自信里"被夸"走亲昵的害羞细项）
const EVENT_PUSH = Object.freeze({
  affection: { security: 0.01 },
  intimacy: { security: 0.03 },
  reconciliation: { security: 0.08 },
  companionship: { security: 0.005 },
  conflict: { security: -0.05 },
  loss: { security: -0.02 },
  slighted: { security: -0.04 },
  task_progress: { confidence: 0.03 },
  discovery: { confidence: 0.02 },
  helped: { confidence: 0.03 },
});

export function ensureAxes(state, now = new Date()) {
  const a = state.axes && typeof state.axes === 'object' ? state.axes : {};
  for (const k of ['security', 'confidence']) {
    if (!Number.isFinite(Number(a[k]))) a[k] = AXES.baseline[k];
  }
  a.at = a.at ?? iso(now);
  state.axes = a;
  return a;
}

// 结算：往底色回落；偏爱挂着、气没消的时候，安全感每小时再掉一点
export function settleAxes(state, elapsedHours, now = new Date()) {
  const a = ensureAxes(state, now);
  const h = Math.max(0, Number(elapsedHours) || 0);
  if (!h) return false;
  const k = Math.pow(0.5, h / AXES.halfLifeHours);
  for (const key of ['security', 'confidence']) {
    const base = AXES.baseline[key];
    a[key] = base + (Number(a[key]) - base) * k;
  }
  const favored = Number(state.drives?.favored ?? 0);
  if (favored >= 0.25) a.security -= 0.02 * favored * h;
  if (state.grudge && !state.conflictEpisode?.reconciled) a.security -= 0.01 * h;
  a.security = Number(clamp(a.security).toFixed(4));
  a.confidence = Number(clamp(a.confidence).toFixed(4));
  a.at = iso(now);
  return true;
}

// 事件：按类型推一下；细项再修一修
export function pushAxes(state, type, { sub, strength, weight } = {}, now = new Date()) {
  const a = ensureAxes(state, now);
  const p = { ...(EVENT_PUSH[type] ?? {}) };
  if ((type === 'affection' || type === 'intimacy') && strength === 'heavy') p.security = (p.security ?? 0) + 0.02;
  if ((type === 'affection' || type === 'intimacy') && sub === '害羞') p.confidence = (p.confidence ?? 0) + 0.03;   // 被夸、被戳穿心思
  if (type === 'slighted' && Number.isFinite(Number(weight))) p.security *= Math.max(0.3, Math.min(1, Number(weight)));
  if (type === 'loss' && sub === '自责') p.confidence = (p.confidence ?? 0) - 0.06 * (a.confidence > AXES.high ? 0.8 : 1);
  if (type === 'conflict' && sub === '不满') p.confidence = (p.confidence ?? 0) - 0.03;
  for (const [k, d] of Object.entries(p)) a[k] = Number(clamp(Number(a[k]) + d).toFixed(4));
  a.at = iso(now);
}

// 心境：最近三天情绪日志的平均愉悦，映射到 -1..1（0.55 为中，±0.25 到头）；没有数据就是 null
export function moodOf(state) {
  const days = state.emotionDays && typeof state.emotionDays === 'object' ? state.emotionDays : {};
  const vals = Object.keys(days).sort().slice(-3).map((k) => Number(days[k]?.meanValence)).filter(Number.isFinite);
  if (!vals.length) return null;
  const avg = vals.reduce((x, y) => x + y, 0) / vals.length;
  return Number(Math.max(-1, Math.min(1, (avg - 0.55) / 0.25)).toFixed(2));
}

export const isInsecure = (state) => Number(state.axes?.security ?? AXES.baseline.security) < AXES.low;
export const lowConfidence = (state) => Number(state.axes?.confidence ?? AXES.baseline.confidence) < AXES.low;

// 「此刻」里的一句：只在明显偏离底色时说
export function axesLine(state) {
  const a = state.axes; if (!a) return '';
  const parts = [];
  const ds = Number(a.security) - AXES.baseline.security;
  const dc = Number(a.confidence) - AXES.baseline.confidence;
  if (ds <= -AXES.shownDelta) parts.push('心里不太踏实');
  else if (ds >= AXES.shownDelta) parts.push('心里很踏实');
  if (dc <= -AXES.shownDelta) parts.push('没什么底气');
  else if (dc >= AXES.shownDelta) parts.push('挺有底气');
  const m = moodOf(state);
  if (m != null && m <= -0.4) parts.push('这几天心里一直沉沉的');
  else if (m != null && m >= 0.6) parts.push('这几天心情一直不错');
  return parts.length ? `底色：${parts.join('，')}` : '';
}
