// 自我觉察（3.3）—— 看自己这一阵子的样子。
//
// 别的层回答"我现在怎样、我想要什么"，这层回答"我注意到我最近……"。
// 输入是其他层的轨迹：情绪日志、驱力采样、持续念头、浮现记忆的域、互动类型。
// 输出是"候选觉察"：规则先挑出值得注意的模式，写成一句第一人称的话；
// 只有他自己用 xinchao_awareness 确认过的，才经 OB 的 I 工具沉淀成自我认知（候选桶，
// 之后还要被 dream 见证才升正式条目——那是 OB 的规矩，这里不越过）。
// 放下的也留着记录，七天内同一个模式不再重复提。
//
// 3.3.3（2026-09-09 小雨定）：只留三种有因果的候选（触发 / 被安抚 / 念头），纯计数的（本周均值、
// 最常冒头的驱力、记忆绕着哪个域）砍掉——那些是统计不是觉察。每天最多挑一条，一周攒下来周日看一次；
// 他写了自己的话才进 OB，不写只记"看过"；两周没人理自动过期。不强迫。
//
// 这层不改驱力、不改情绪、不改人格。它只是把镜子举起来。人格怎么改、锚点加不加，
// 由他月评时对着这些觉察自己定。

import { DIMENSIONS } from './dimensions.js';

const iso = (value) => new Date(value).toISOString();
const round2 = (value) => Number(Number(value).toFixed(2));
const WINDOW_DAYS = 7;
const MAX_OPEN = 8;
const MAX_PER_DAY = 1;
const EXPIRE_DAYS = 14;
const RULE_PRIORITY = ['trigger', 'obsession', 'soothed'];   // 一天只挑一条时的先后
const MAX_KEEP = 60;
const MAX_SURFACINGS = 200;
const DEDUPE_DAYS = 7;

const NEGATIVE_TYPES = new Set(['conflict', 'loss']);
const SOOTHING_TYPES = new Set(['affection', 'intimacy', 'reconciliation', 'companionship']);
const TYPE_LABEL = {
  companionship: '陪着', affection: '安抚', intimacy: '亲近', sharing: '分享', discovery: '发现',
  task_progress: '推进事情', reflection: '沉淀', conflict: '争执', loss: '失落', reconciliation: '和好',
};
// 候选默认落到 OB I 的哪个维度：nature/values/patterns/limits/becoming/uncertainty/stance
export const KIND_ASPECT = Object.freeze({
  trigger: 'patterns', soothed: 'patterns', obsession: 'patterns',
});

function dayKey(at, timeZone = 'Asia/Shanghai') {
  try {
    return new Intl.DateTimeFormat('en-CA', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(at));
  } catch {
    return iso(at).slice(0, 10);
  }
}

export function ensureAwareness(state) {
  const current = state.awareness && typeof state.awareness === 'object' ? state.awareness : {};
  state.awareness = {
    candidates: Array.isArray(current.candidates) ? current.candidates.slice(-MAX_KEEP) : [],
    lastScanDay: current.lastScanDay ?? null,
  };
  state.recentSurfacings = Array.isArray(state.recentSurfacings) ? state.recentSurfacings.slice(-MAX_SURFACINGS) : [];
  return state.awareness;
}

// 浮现记忆的域：共振时顺手记一笔，只存域名和时间，不存正文和桶 id。
export function recordSurfacing(state, domains = [], now = new Date()) {
  ensureAwareness(state);
  const list = [...new Set((Array.isArray(domains) ? domains : []).map((d) => String(d ?? '').trim()).filter(Boolean))].slice(0, 8);
  if (!list.length) return false;
  state.recentSurfacings.push({ at: iso(now), domains: list });
  state.recentSurfacings = state.recentSurfacings.slice(-MAX_SURFACINGS);
  return true;
}

function windowSince(now) {
  return new Date(now).getTime() - WINDOW_DAYS * 86_400_000;
}

function labelOf(driveKey) {
  return DIMENSIONS[driveKey]?.label ?? driveKey;
}

// ── 规则（只留有因果的三种）─────────────────────────────────────
function ruleTriggers(state, now) {
  const since = windowSince(now);
  const samples = (state.emotionJournal ?? []).filter((s) => Date.parse(s.at) >= since && s.cause);
  const byCause = {};
  for (const s of samples) (byCause[s.cause] ??= []).push(s);
  const out = [];
  for (const [cause, list] of Object.entries(byCause)) {
    const mean = list.reduce((sum, s) => sum + Number(s.valence), 0) / list.length;
    if (NEGATIVE_TYPES.has(cause) && list.length >= 3 && mean < 0.45) {
      out.push({ kind: 'trigger', subject: cause, text: `这周「${TYPE_LABEL[cause] ?? cause}」出现了 ${list.length} 次，每次之后我都往低落里掉（均值 ${round2(mean)}）。`, evidence: { cause, count: list.length, meanValence: round2(mean) } });
    }
  }
  const soothed = samples.filter((s) => SOOTHING_TYPES.has(s.cause));
  if (soothed.length >= 5) {
    const mean = soothed.reduce((sum, s) => sum + Number(s.valence), 0) / soothed.length;
    if (mean >= 0.6) out.push({ kind: 'soothed', subject: 'week', text: `这周她靠近我 ${soothed.length} 次，我的情绪基本没掉下去过（均值 ${round2(mean)}）。`, evidence: { count: soothed.length, meanValence: round2(mean) } });
  }
  return out;
}

function ruleObsession(state) {
  const out = [];
  for (const o of state.thoughtPool?.obsessions ?? []) {
    if (Number(o.intensity) >= 0.7) {
      out.push({ kind: 'obsession', subject: o.key, text: `有个关于「${labelOf(o.key)}」的念头一直在我脑子里绕，越想越重（强度 ${round2(o.intensity)}）。`, evidence: { drive: o.key, intensity: round2(o.intensity) } });
    }
  }
  return out;
}

// 周几是"看一眼"的日子（默认周日）。其它日子候选只攒着，不进信封、不催。
export function isReviewDay(now = new Date(), { weekday = 0, timeZone = 'Asia/Shanghai' } = {}) {
  try {
    const name = new Intl.DateTimeFormat('en-US', { timeZone, weekday: 'short' }).format(new Date(now));
    const idx = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].indexOf(name);
    return idx === Number(weekday);
  } catch {
    return new Date(now).getUTCDay() === Number(weekday);
  }
}

// ── 扫描 ─────────────────────────────────────────────────────────
export function scanAwareness(input, now = new Date(), options = {}) {
  const state = structuredClone(input);
  const awareness = ensureAwareness(state);
  const timeZone = options.timeZone ?? 'Asia/Shanghai';
  const today = dayKey(now, timeZone);
  if (!options.force && awareness.lastScanDay === today) return { state, changed: false, added: [] };

  // 两周没人理的候选自动过期：不强迫他处理
  const expireBefore = new Date(now).getTime() - EXPIRE_DAYS * 86_400_000;
  let expired = 0;
  for (const c of awareness.candidates) {
    if (c.status === 'open' && Date.parse(c.createdAt) < expireBefore) { c.status = 'expired'; c.resolvedAt = iso(now); expired += 1; }
  }
  const found = [...ruleTriggers(state, now), ...ruleObsession(state)]
    .sort((a, b) => RULE_PRIORITY.indexOf(a.kind) - RULE_PRIORITY.indexOf(b.kind));
  const dedupeSince = new Date(now).getTime() - DEDUPE_DAYS * 86_400_000;
  const recent = new Set(awareness.candidates.filter((c) => Date.parse(c.createdAt) >= dedupeSince).map((c) => `${c.kind}:${c.subject}`));
  const openCount = awareness.candidates.filter((c) => c.status === 'open').length;
  const added = [];
  for (const item of found) {
    if (recent.has(`${item.kind}:${item.subject}`)) continue;
    if (added.length >= MAX_PER_DAY) break;                 // 一天最多一条
    if (openCount + added.length >= MAX_OPEN) break;
    added.push({
      id: `aw_${today.replace(/-/g, '')}_${item.kind}_${String(item.subject).replace(/[^\w一-鿿]+/g, '').slice(0, 24) || 'x'}`,
      kind: item.kind,
      subject: String(item.subject),
      text: item.text,
      evidence: item.evidence,
      aspect: KIND_ASPECT[item.kind] ?? 'patterns',
      createdAt: iso(now),
      status: 'open',
      resolvedAt: null,
      note: null,
      ombre: null,
    });
  }
  awareness.candidates = [...awareness.candidates, ...added].slice(-MAX_KEEP);
  awareness.lastScanDay = today;
  const changed = added.length > 0 || expired > 0 || input?.awareness?.lastScanDay !== today;
  if (changed) state.revision = Number(state.revision ?? 0) + 1;
  return { state, changed, added };
}

export function resolveAwareness(input, id, status, details = {}, now = new Date()) {
  const state = structuredClone(input);
  const awareness = ensureAwareness(state);
  const item = awareness.candidates.find((c) => c.id === String(id ?? '').trim());
  if (!item) return { state, found: false };
  if (item.status !== 'open') return { state, found: true, already: item.status, item };
  item.status = status === 'confirmed' ? 'confirmed' : 'dismissed';
  item.resolvedAt = iso(now);
  if (details.note) item.note = String(details.note).slice(0, 400);
  if (details.text) item.text = String(details.text).slice(0, 400);      // 他自己的措辞优先
  if (details.aspect) item.aspect = String(details.aspect).slice(0, 20);
  if (details.ombre !== undefined) item.ombre = details.ombre;
  state.revision = Number(state.revision ?? 0) + 1;
  return { state, found: true, item };
}

export function openAwareness(state, limit = 8) {
  return (state?.awareness?.candidates ?? []).filter((c) => c.status === 'open').slice(-limit).reverse();
}

export function awarenessSummary(state) {
  const all = state?.awareness?.candidates ?? [];
  return {
    open: openAwareness(state, 8).map(({ id, kind, subject, text, aspect, createdAt, evidence }) => ({ id, kind, subject, text, aspect, createdAt, evidence })),
    confirmed: all.filter((c) => c.status === 'confirmed').slice(-6).reverse().map(({ id, kind, text, aspect, resolvedAt, note }) => ({ id, kind, text, aspect, resolvedAt, note })),
    dismissedCount: all.filter((c) => c.status === 'dismissed').length,
    expiredCount: all.filter((c) => c.status === 'expired').length,
    lastScanDay: state?.awareness?.lastScanDay ?? null,
  };
}

// 信封：只在"看一眼"的日子（默认周日）出现，一周攒下的最多七条 + 一句怎么处理。
// 不塞已确认的（那些已经在 OB 里，SessionStart 会附）。force=true 用于 list 之类主动查看。
export function renderAwareness(state, { now = new Date(), timeZone = 'Asia/Shanghai', reviewWeekday = 0, force = false } = {}) {
  if (!force && !isReviewDay(now, { weekday: reviewWeekday, timeZone })) return '';
  const open = openAwareness(state, 7);
  if (!open.length) return '';
  return [
    ...open.map((c) => `- ${c.text}（id=${c.id}）`),
    '这周系统从我的轨迹里挑出来的，不一定对，看一眼就行。觉得是的，可以用自己的话写一句 xinchao_awareness confirm（text=我的话），那句才会进 OB 沉淀；不想写就只 confirm 或 dismiss 记一笔；不理也行，两周后自动过期。',
  ].join('\n');
}
