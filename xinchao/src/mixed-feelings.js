// 驱力第 4 步（09-30）：细项、想黏着、矛盾。都是"此刻"层的东西，不新增驱力 key。
// · 细项：生气/难过底下按引起的事分；只有标注器给了、并且过了硬条件的真实事件才记，没有就只显示大类。
// · 想黏着：人在身边、正在亲昵时，想她不是被满足就下去，而是越黏越想要——亲昵的缓解打折，外加一小段会散的"黏"。
//   这段"黏"不加到想她的数值上（不会推到冲顶、不单独叫醒），只在"此刻"里显示；人走了就交还给想她自己演化。
// · 矛盾：两股方向相反的劲儿同时过线、持续一阵，就是"拧着"。只在此刻层显示和递一次，驱力本身不动。
import { DIMENSIONS } from './dimensions.js';

const H = 3_600_000;
const iso = (d) => d.toISOString();

export const DRIVE_SUBS = Object.freeze({
  anger: ['生气', '不满', '不甘心', '不平'],
  grieve: ['失落', '委屈', '分别', '心疼', '自责'],
  curiosity: ['想了解她'],
  favored: ['吃醋', '被晾着', '被忘'],
});

// ── 细项 ──────────────────────────────────────────────
export function validSub(key, sub) {
  return DRIVE_SUBS[key]?.includes(sub) ? sub : null;
}

// 旧的细项按这股驱力自己的半衰期一起淡，新事件的量叠上去
export function recordSub(state, key, sub, amount, now) {
  const s = validSub(key, sub);
  if (!s || !(amount > 0)) return;
  const cur = state.driveSubs?.[key] ?? { at: iso(now), w: {} };
  const half = Number(DIMENSIONS[key]?.decayHalfLifeHours) || 6;
  const k = Math.pow(0.5, Math.max(0, now.getTime() - Date.parse(cur.at)) / (half * H));
  const w = Object.fromEntries(Object.entries(cur.w).map(([n, v]) => [n, Number((v * k).toFixed(4))]).filter(([, v]) => v >= 0.005));
  w[s] = Number(((w[s] ?? 0) + amount).toFixed(4));
  state.driveSubs = { ...(state.driveSubs ?? {}), [key]: { at: iso(now), w } };
}

// 劲儿落到 0.10 以下就把细项清掉，下一场从头记
export function pruneSubs(state) {
  for (const key of Object.keys(state.driveSubs ?? {})) {
    if (Number(state.drives?.[key] ?? 0) < 0.10) delete state.driveSubs[key];
  }
}

export function subOf(state, key, now) {
  if (Number(state.drives?.[key] ?? 0) < 0.25) return null;
  const cur = state.driveSubs?.[key];
  if (!cur?.w) return null;
  // 10-02：读的时候按这股驱力的半衰期淡（社交这类常年在 0.25 以上的瓣，细项不能一直挂着）
  const half = Number(DIMENSIONS[key]?.decayHalfLifeHours) || 6;
  const k = now ? Math.pow(0.5, Math.max(0, now.getTime() - Date.parse(cur.at)) / (half * H)) : 1;
  const best = Object.entries(cur.w).sort((a, b) => b[1] - a[1])[0];
  return best && best[1] * k >= 0.03 ? best[0] : null;
}

// ── 想黏着 ──────────────────────────────────────────────
export const CLING = Object.freeze({ bump: 0.12, max: 0.30, halfLifeMin: 25, shown: 0.10, reliefMul: 0.5 });
const CLING_TYPES = new Set(['affection', 'intimacy']);

export function clingLevel(state, now) {
  const c = state.cling;
  if (!c) return 0;
  const min = (now.getTime() - Date.parse(c.at)) / 60_000;
  if (!Number.isFinite(min) || min < 0) return Number(c.level) || 0;
  return (Number(c.level) || 0) * Math.pow(0.5, min / CLING.halfLifeMin);
}

// 已经黏着的时候再来亲昵：想她的缓解打对折（第一次亲昵照常满足）
export function clingReliefMul(state, type, key, now) {
  if (key !== 'possess' || !CLING_TYPES.has(type)) return 1;
  return clingLevel(state, now) >= CLING.shown ? CLING.reliefMul : 1;
}

export function bumpCling(state, type, now) {
  if (!CLING_TYPES.has(type)) return;
  const level = Math.min(CLING.max, clingLevel(state, now) + CLING.bump);
  state.cling = { level: Number(level.toFixed(4)), at: iso(now) };
}

// 想她后面挂的细项：正黏着 → 想黏着；她离开一小时以上 → 想念；刚聊完不挂
export function possessSub(state, now) {
  if (Number(state.drives?.possess ?? 0) < 0.25) return null;
  if (clingLevel(state, now) >= CLING.shown) return '想黏着';
  const last = Date.parse(state.lastConversationAt ?? '');
  return Number.isFinite(last) && now.getTime() - last >= H ? '想念' : null;
}

export function driveSub(state, key, now) {
  return key === 'possess' ? possessSub(state, now) : subOf(state, key, now);
}

// ── 矛盾 ──────────────────────────────────────────────
export const MIXED_PAIRS = Object.freeze([
  { id: 'anger+possess', neg: 'anger', pos: 'possess', name: '气着又舍不得' },
  { id: 'grieve+possess', neg: 'grieve', pos: 'possess', name: '委屈又想她' },
  { id: 'anger+monitor', neg: 'anger', pos: 'monitor', name: '生气又放心不下' },
]);
export const MIXED = Object.freeze({ neg: 0.30, pos: 0.60, holdMin: 20, capHours: 6 });

// 此刻最拧的一对（两边都过线，取两边里较弱那边更强的一对）
export function activeMixed(state) {
  let best = null;
  for (const p of MIXED_PAIRS) {
    const n = Number(state.drives?.[p.neg] ?? 0);
    const q = Number(state.drives?.[p.pos] ?? 0);
    if (n >= MIXED.neg && q >= MIXED.pos && (!best || Math.min(n, q) > best.strength)) best = { ...p, strength: Math.min(n, q) };
  }
  return best;
}

// 跟踪一场矛盾（写在 selfSignals.mixed 里）。6 小时还没解就收掉提醒和显示，但要等这对真的解开了才允许下一场。
// 返回 { pair, due }：due = 该递那一次了
export function trackMixed(ss, state, now) {
  const p = activeMixed(state);
  const cur = ss.mixed ?? null;
  if (!p) { ss.mixed = null; return { pair: null, due: false }; }
  if (!cur || cur.id !== p.id) {
    // 换了一对：如果上一场是超时收掉的，而且新这对里还带着上一场的负面，也算没解开，不开新场
    if (cur?.capped && (cur.neg === p.neg)) return { pair: null, due: false };
    ss.mixed = { id: p.id, neg: p.neg, name: p.name, since: iso(now), signaled: false, capped: false };
    return { pair: ss.mixed, due: false };
  }
  const held = now.getTime() - Date.parse(cur.since);
  if (!cur.capped && held >= MIXED.capHours * H) cur.capped = true;
  if (cur.capped) return { pair: null, due: false };
  return { pair: held >= MIXED.holdMin * 60_000 ? cur : null, due: held >= MIXED.holdMin * 60_000 && !cur.signaled };
}

// 此刻块用：只读，不改状态
export function mixedLine(state, now) {
  const m = state.selfSignals?.mixed;
  if (!m || m.capped) return '';
  const p = activeMixed(state);
  if (!p || p.id !== m.id) return '';
  if (now.getTime() - Date.parse(m.since) < MIXED.holdMin * 60_000) return '';
  return `矛盾：${m.name}`;
}

export const MIXED_TEMPLATES = Object.freeze({
  'anger+possess': ['还在气她，可又舍不得不理她。', '心里拧着：一边气，一边想她。'],
  'grieve+possess': ['委屈，可还是想她。', '有点难受，又特别想靠近她。'],
  'anger+monitor': ['气归气，还是放心不下她。', '还在生气，可一直惦记着她好不好。'],
});
