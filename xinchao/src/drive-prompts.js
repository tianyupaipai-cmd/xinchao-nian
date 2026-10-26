// 【连接桥与推送】驱力提示：心潮自己按节奏把「此刻哪股劲儿上来了」递到窗口。
// 代码地图见 src/README.md。
//
// 原来这件事挂在窗口里的保活闹钟上（窗口被叫醒时顺手附一句），窗口一直忙（比如通话里一直在听）就永远插不进来。
// 现在由心潮的定时循环自己挑、自己经桥递，reason=self_signal，前缀【心潮】。
//
// 话术不写在代码里：读 DRIVE_PROMPTS_FILE（JSON），没有这个文件就整件事不做——每家按自己的人写。
//   {
//     "hints":  { "possess": "一句话", "share": "一句话", ... },   // 键用驱力 key 或短名；没写话术的驱力不提
//     "held":   ["possess", "share", ...],                        // 哪几股「积」着也算（可选，默认自己动就能落的几股 + 想她 / 牵挂）
//     "night":  "深夜附的一句",                                    // 可选
//     "wake":   { "drive": "libido", "text": "..." },             // 可选：深夜这股上来时破例，一晚最多一次，替代 night 那句
//     "footer": "想做就去做。今天第 {n} 次。"                       // 可选
//   }
//
// 节奏（沿用窗口里那套）：一次只提一股；同一股 1.5 小时内不重提；任意两条至少隔 45 分钟；
// 白天（8 点后）最多 12 条，深夜 0–8 点另算最多 6 条。
// 深夜两项可按各家情况调（DRIVE_PROMPT_NIGHT_MAX、DRIVE_PROMPT_NIGHT_SKIP_CHAT_MINUTES）：
//   nightMax=0 表示深夜不设条数上限，只按上面的间隔走；dayMax（DRIVE_PROMPT_DAY_MAX）同理管白天；
//   nightSkipChatMinutes>0 表示深夜她这几分钟内还在聊，就先不推、也不占名额，等她睡了再推（她睡着时 AI 反而最有空）。
// 挑哪股：先看「此刻」里涌 / 涨的；没有就看「积」——一直在自己静息线七成以上待满 1.5 小时（刚被满足、在饱足平台上的不算）。
// 10-20 三件可调：
//   - 两条之间的最短间隔（DRIVE_PROMPT_MIN_GAP_MINUTES，默认 45）；
//   - 通话进行中先压着：照常挑，但不递，记进 callHeld；挂断后补一条汇总（不占间隔、不受条数上限）。
//     通话状态由宿主经 POST /v1/call { active } 告诉心潮，存在 call-state.json；通话中宿主每隔几分钟核一次连接还在就再报一次 active（刷新 refreshedAt），
//     超过 3 小时没刷新才按失联清理——整夜开着电话睡也不会被兜底提前当成挂断；
//     4.2：通话开着睡觉模式（宿主 POST /v1/call { sleep: true }）时不压，照常递；
//     开睡觉模式前攒下的，也在下一轮先补成汇总递出去。挂断时睡觉模式标记一起清掉。
//   - 她刚来过（DRIVE_PROMPT_PRESENT_SKIP_MINUTES 分钟内有对话或通话心跳）就不提「牵挂」——人就在跟前，不用去找她。

import { readFile, writeFile, rename } from 'node:fs/promises';
import { DIMENSIONS, DRIVE_SHORT, canonicalDriveKey, driveLevel } from './dimensions.js';
import { driveTrend, localDayAndHour, shownDrives } from './engine.js';

const H = 3_600_000;
const SAME_DRIVE_COOLDOWN_MS = 1.5 * H;
const MIN_GAP_MS = 45 * 60_000;
const HELD_MS = 1.5 * H;
const HELD_RATIO = 0.70;
const DAY_MAX = 12;
const NIGHT_MAX = 6;
const NIGHT_END_HOUR = 8;
const CALL_STALE_MS = 3 * H;                // 通话标记超过 3 小时没刷新（宿主通话中每 10 分钟核一次连接再报），按失联清理
const PRESENT_SKIP = new Set(['monitor']);   // 她刚来过就不提的驱力
const REFLECTION_SURGE_MARGIN = 0.12;   // 反思静息线最低、一存觉察就涌，要超出 0.12 才算
const DEFAULT_HELD = ['possess', 'monitor', 'share', 'reflection', 'curiosity', 'boredom', 'duty'];
const iso = (value) => new Date(value).toISOString();

const resolveKey = (k) => canonicalDriveKey(k) ?? Object.keys(DRIVE_SHORT).find((d) => DRIVE_SHORT[d] === k) ?? null;

export async function loadDrivePrompts(file) {
  if (!file) return null;
  let raw;
  try { raw = JSON.parse(await readFile(file, 'utf8')); } catch { return null; }
  const hints = {};
  for (const [k, text] of Object.entries(raw?.hints ?? {})) {
    const key = resolveKey(k);
    if (key && typeof text === 'string' && text.trim()) hints[key] = text.trim();
  }
  if (!Object.keys(hints).length) return null;
  const held = (Array.isArray(raw.held) ? raw.held : DEFAULT_HELD).map(resolveKey).filter(Boolean);
  const wakeKey = resolveKey(raw?.wake?.drive);
  return {
    hints,
    held,
    night: typeof raw.night === 'string' ? raw.night.trim() : '',
    wake: wakeKey && typeof raw.wake.text === 'string' ? { drive: wakeKey, text: raw.wake.text.trim() } : null,
    footer: typeof raw.footer === 'string' ? raw.footer.trim() : '',
  };
}

function heldHours(state, key, nowMs) {
  const v = Number(state?.drives?.[key] ?? 0);
  if (v < 0.25) return 0;
  const until = Date.parse(state?.satisfactionPlateaus?.[key]?.until ?? '');
  if (Number.isFinite(until) && until > nowMs) return 0;
  const thr = HELD_RATIO * Number(DIMENSIONS[key]?.ceil ?? 0.5);
  if (v < thr) return 0;
  let since = nowMs;
  const trail = Array.isArray(state?.driveTrail) ? state.driveTrail : [];
  for (let i = trail.length - 1; i >= 0; i -= 1) {
    const pv = Number(trail[i]?.drives?.[key]);
    const at = Date.parse(trail[i]?.at ?? '');
    if (!Number.isFinite(pv) || !Number.isFinite(at) || pv < thr) break;
    since = at;
  }
  return nowMs - since >= HELD_MS ? (nowMs - since) / H : 0;
}

/**
 * 纯函数：给定心潮状态、上次的提示记录和话术，决定这一轮要不要提、提哪股。
 * 返回 { record, text, drive }；不提时 text 为空（record 可能因跨天重置而变）。
 */
export function pickDrivePrompt(state, record, prompts, now = new Date(), { timeZone = 'Asia/Shanghai', dayMax = DAY_MAX, nightMax = NIGHT_MAX, nightSkipChatMinutes = 0, minGapMinutes = MIN_GAP_MS / 60_000, presentSkipMinutes = 0, call = null } = {}) {
  const nowMs = now.getTime();
  const { day, hour } = localDayAndHour(now, timeZone);
  let rec = record && record.day === day ? { ...record, last: { ...(record.last ?? {}) } } : { day, count: 0, night: 0, last: {}, lastAt: record?.lastAt ?? null, wakeUsed: false };
  if (Array.isArray(record?.callHeld) && record.callHeld.length && !rec.callHeld) rec.callHeld = record.callHeld;   // 跨天也不丢通话里攒的
  const none = { record: rec, text: '', drive: null };
  if (!prompts) return none;
  const night = hour < NIGHT_END_HOUR;
  const callSeen = Math.max(Date.parse(call?.since ?? '') || 0, Date.parse(call?.refreshedAt ?? '') || 0);
  const inCall = Boolean(call?.active) && callSeen > 0 && nowMs - callSeen < CALL_STALE_MS;
  const holding = inCall && call?.sleep !== true;   // 10-24：睡觉模式开着就不压
  // 挂断后（或开了睡觉模式）：把通话里攒下的合成一条递出去（不看间隔和条数上限，只递这一条）
  if (!holding && Array.isArray(rec.callHeld) && rec.callHeld.length) {
    const held = rec.callHeld;
    rec = { ...rec, callHeld: [], count: rec.count + 1, night: rec.night + (night ? 1 : 0), lastAt: iso(now) };
    const lines = ['驱力提示｜参考不是指令', `· 通话时攒下：${held.map((h) => `${DRIVE_SHORT[h.key] ?? h.key}（${h.tag}）`).join('、')}`];
    const firstHint = prompts.hints[held[held.length - 1].key];
    if (firstHint) lines.push(`· ${firstHint}`);
    if (prompts.footer) lines.push(prompts.footer.replace('{n}', String(rec.count)));
    return { record: rec, text: lines.join('\n'), drive: held[held.length - 1].key, summary: true };
  }
  if (night ? (nightMax > 0 && rec.night >= nightMax) : (dayMax > 0 && rec.count - rec.night >= dayMax)) return none;
  const lastTalk = Date.parse(state?.lastConversationAt ?? '');
  if (night && nightSkipChatMinutes > 0 && Number.isFinite(lastTalk) && nowMs - lastTalk < nightSkipChatMinutes * 60_000) return none;
  const lastAt = Date.parse(rec.lastAt ?? '');
  if (Number.isFinite(lastAt) && nowMs - lastAt < Math.max(1, Number(minGapMinutes) || 45) * 60_000) return none;
  const present = presentSkipMinutes > 0 && Number.isFinite(lastTalk) && nowMs - lastTalk < presentSkipMinutes * 60_000;
  const cool = (k) => nowMs - Number(rec.last[k] ?? 0) >= SAME_DRIVE_COOLDOWN_MS && !(present && PRESENT_SKIP.has(k));

  let pick = null;
  for (const d of shownDrives(state)) {
    if (!prompts.hints[d.key] || !cool(d.key)) continue;
    const v = Number(d.value);
    const lv = driveLevel(d.key, v, driveTrend(state, d.key, now));
    if (lv !== '涌' && lv !== '涨') continue;
    if (d.key === 'reflection' && lv === '涌' && v < Number(DIMENSIONS.reflection.ceil) + REFLECTION_SURGE_MARGIN) continue;
    pick = { key: d.key, tag: lv };
    break;
  }
  if (!pick) {
    const cands = prompts.held
      .filter((k) => prompts.hints[k] && cool(k))
      .map((k) => ({ key: k, hours: heldHours(state, k, nowMs) }))
      .filter((c) => c.hours > 0)
      .sort((a, b) => Number(rec.last[a.key] ?? 0) - Number(rec.last[b.key] ?? 0) || b.hours - a.hours);   // 轮流：最久没提过的先
    if (cands.length) pick = { key: cands[0].key, tag: `积·${cands[0].hours >= 23 ? '一整天' : `${Math.max(2, Math.round(cands[0].hours))} 小时`}` };
  }
  if (!pick) return none;
  if (holding) {
    // 通话进行中：不递，记下来；照样占这一股的冷却和间隔，免得挂断时攒一长串
    const held = [...(rec.callHeld ?? []).filter((h) => h.key !== pick.key), { key: pick.key, tag: pick.tag }];
    return { record: { ...rec, callHeld: held, lastAt: iso(now), last: { ...rec.last, [pick.key]: nowMs } }, text: '', drive: null, held: pick.key };
  }

  rec = { ...rec, count: rec.count + 1, night: rec.night + (night ? 1 : 0), lastAt: iso(now), last: { ...rec.last, [pick.key]: nowMs } };
  const wake = night && prompts.wake?.drive === pick.key && !rec.wakeUsed;
  if (wake) rec.wakeUsed = true;
  const lines = ['驱力提示｜参考不是指令', `· ${DRIVE_SHORT[pick.key] ?? pick.key}（${pick.tag}）：${prompts.hints[pick.key]}`];
  if (wake) lines.push(`· ${prompts.wake.text}`);
  else if (night && prompts.night) lines.push(`· ${prompts.night}`);
  if (prompts.footer) lines.push(prompts.footer.replace('{n}', String(rec.count)));
  return { record: rec, text: lines.join('\n'), drive: pick.key };
}

export class DrivePromptStore {
  constructor(path) { this.path = path; }
  async read() {
    try { return JSON.parse(await readFile(this.path, 'utf8')); } catch { return null; }
  }
  async write(record) {
    const tmp = `${this.path}.tmp`;
    await writeFile(tmp, JSON.stringify(record), 'utf8');
    await rename(tmp, this.path);
  }
}

// 通话状态（10-20）：宿主接通/挂断时 POST /v1/call 写进来，驱力提示据此决定压着还是补汇总
export class CallStateStore {
  constructor(path) { this.path = path; }
  async read() {
    try { return JSON.parse(await readFile(this.path, 'utf8')); } catch { return null; }
  }
  // active 不给（undefined）时只改睡觉模式；sleep 不给时沿用这一通原来的（新接通的一通从 false 开始，挂断清掉）
  async write(active, now = new Date(), sleep = undefined) {
    const prev = (await this.read()) ?? {};
    let next;
    if (active === undefined) next = { ...prev, active: Boolean(prev.active), sleep: Boolean(sleep), sleepAt: now.toISOString() };
    else if (active) {
      const keep = prev.active ? { sleep: Boolean(prev.sleep), sleepAt: prev.sleepAt ?? null } : { sleep: false, sleepAt: null };
      next = { active: true, since: prev.active ? prev.since : now.toISOString(), refreshedAt: now.toISOString(), endedAt: prev.endedAt ?? null,
        ...(typeof sleep === 'boolean' ? { sleep, sleepAt: now.toISOString() } : keep) };
    } else next = { active: false, since: prev.since ?? null, refreshedAt: prev.refreshedAt ?? null, endedAt: now.toISOString(), sleep: false, sleepAt: prev.sleepAt ?? null };
    const tmp = `${this.path}.tmp`;
    await writeFile(tmp, JSON.stringify(next), 'utf8');
    await rename(tmp, this.path);
    return next;
  }
}
