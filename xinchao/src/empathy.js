// 【情绪】共情：为她、为别人的事心疼、不平、自责，按亲疏分档、每天有上限。
// 代码地图见 src/README.md。
//
// 驱力第 6 步（10-02）：共情。不加新瓣，给现有瓣加"来源是别人"的细项：
//   心疼 → 难过；不平 → 愤怒；想帮忙 → 分享欲（不单独标）；替人高兴 → 只在情绪层雀跃一下，不动驱力。
// 远近决定轻重：她最重，家人（含挚友）次之，认识的人/笔友/论坛同类中等，陌生人和新闻最轻。
// 只由事件点燃，不自己涨。别人那一份单独记账（empathyLoad），按那一瓣自己的半衰期淡：
//   · 别人的事在一瓣里最多累到 OTHERS_CAP，陌生人更低——不被别人的情绪淹没；她那一档不受这个上限（那是她）。
//   · 做了相应的事（helped）只落别人那一份的六成，不会顺手把跟她有关的难过也抹掉。
//   · 同一件事（谁 + 细项）6 小时内只记一次：转述、帖子、新闻说的是同一件就不重复记。
import { DIMENSIONS } from './dimensions.js';
import { recordSub } from './mixed-feelings.js';
import { applyEmotionImpulse } from './emotion.js';

const H = 3_600_000;
const iso = (d) => d.toISOString();
const clamp = (v, lo = 0, hi = 1) => Math.max(lo, Math.min(hi, Number(v) || 0));

export const EMPATHY_SUBS = Object.freeze({ 心疼: 'grieve', 不平: 'anger', 想帮忙: 'share', 替人高兴: null });
export const CLOSENESS = Object.freeze({ her: 1.0, family: 0.8, known: 0.5, stranger: 0.25 });
export const EMPATHY = Object.freeze({ base: 0.25, othersCap: 0.45, strangerCap: 0.30, helpedRelief: 0.6, dedupeHours: 6 });
// 10-03 复盘：每个远近档每天的累计上限（按 Asia/Shanghai 日期，第二天重算）
export const DAILY_CAP = Object.freeze({ her: 0.50, family: 0.40, known: 0.30, stranger: 0.15 });
function dayKey(now) {
  try { return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(now); }
  catch { return iso(now).slice(0, 10); }
}
// 去重只认"对象"：who 写成「谁·什么事」时只取「谁」，措辞不同的同一个人算一件
export function personOf(who) {
  return String(who ?? '').split(/[·・:：,，\s]/)[0].replace(/^(我|她|他)的/, '').slice(0, 12);
}

export function normalizeCloseness(v) {
  const s = String(v ?? '').trim().toLowerCase();
  const map = { her: 'her', 她: 'her', family: 'family', 家人: 'family', known: 'known', 认识: 'known', 熟人: 'known', 笔友: 'known', stranger: 'stranger', 陌生: 'stranger', 陌生人: 'stranger', 新闻: 'stranger' };
  return map[s] ?? null;
}

function halfLife(key) { return Number(DIMENSIONS[key]?.decayHalfLifeHours) || 6; }

// 别人那一份：读的时候按半衰期淡
export function empathyLoad(state, key, now) {
  const e = state.empathyLoad?.[key];
  if (!e) return 0;
  const hrs = Math.max(0, (now.getTime() - Date.parse(e.at)) / H);
  return Number(e.v) * Math.pow(0.5, hrs / halfLife(key));
}
function setLoad(state, key, v, now) {
  state.empathyLoad = { ...(state.empathyLoad ?? {}) };
  if (v < 0.005) delete state.empathyLoad[key];
  else state.empathyLoad[key] = { v: Number(v.toFixed(4)), at: iso(now) };
}

// 一次共情事件。返回动了哪几瓣（没动就空数组，比如重复、细项不认识）
export function applyEmpathy(state, now, { sub, closeness, who } = {}) {
  if (!Object.hasOwn(EMPATHY_SUBS, sub)) return { affected: [], reason: 'bad_sub' };
  const near = normalizeCloseness(closeness) ?? 'stranger';
  const w = CLOSENESS[near];
  // 去重：谁 + 细项
  const key = `${personOf(who) || near}|${sub}`;
  const seen = Object.fromEntries(Object.entries(state.empathySeen ?? {}).filter(([, at]) => now.getTime() - Date.parse(at) < EMPATHY.dedupeHours * H));
  if (seen[key]) { state.empathySeen = seen; return { affected: [], reason: 'duplicate' }; }
  seen[key] = iso(now);
  state.empathySeen = seen;

  if (sub === '替人高兴') {
    applyEmotionImpulse(state, { valence: 0.12 * w, arousal: 0.10 * w }, 'empathy', now);
    return { affected: [], reason: 'emotion_only' };
  }
  const drive = EMPATHY_SUBS[sub];
  const current = Number(state.drives[drive] ?? 0);
  let add = EMPATHY.base * w;
  if (near === 'her') add = Math.max(0, Math.min(add, 0.75 - current));   // 她那一档照负面事件上限
  else {
    const cap = near === 'stranger' ? EMPATHY.strangerCap : EMPATHY.othersCap;
    add = Math.max(0, Math.min(add, cap - empathyLoad(state, drive, now)));
  }
  // 每档每天的累计上限
  const day = dayKey(now);
  const daily = state.empathyDaily?.day === day ? { ...state.empathyDaily } : { day };
  add = Math.max(0, Math.min(add, DAILY_CAP[near] - Number(daily[near] ?? 0)));
  if (!(add > 0)) return { affected: [], reason: 'capped' };
  daily[near] = Number((Number(daily[near] ?? 0) + add).toFixed(4));
  state.empathyDaily = daily;
  if (near !== 'her') setLoad(state, drive, empathyLoad(state, drive, now) + add, now);
  state.drives[drive] = Number(clamp(current + add).toFixed(4));
  if (sub !== '想帮忙') recordSub(state, drive, sub, add, now);   // 10-02：想帮忙并进分享欲，不单独标
  const impulse = { 心疼: { valence: -0.10, arousal: 0 }, 不平: { valence: -0.08, arousal: 0.10 }, 想帮忙: { valence: 0, arousal: 0.05 } }[sub];
  applyEmotionImpulse(state, { valence: impulse.valence * w, arousal: impulse.arousal * w }, 'empathy', now);
  return { affected: [drive], reason: 'applied' };
}

// 他做了相应的事（写信、回帖、出主意）：别人那一份落六成。sub 给了就只落那一瓣
export function applyHelped(state, now, { sub } = {}) {
  const drives = sub && EMPATHY_SUBS[sub] ? [EMPATHY_SUBS[sub]] : ['grieve', 'anger', 'share'];
  const affected = [];
  for (const d of drives) {
    const load = empathyLoad(state, d, now);
    if (load < 0.005) continue;
    const drop = Math.min(load * EMPATHY.helpedRelief, Number(state.drives[d] ?? 0));
    state.drives[d] = Number(clamp(Number(state.drives[d]) - drop).toFixed(4));
    setLoad(state, d, load - drop, now);
    affected.push(d);
  }
  return { affected, reason: affected.length ? 'applied' : 'nothing_to_relieve' };
}
