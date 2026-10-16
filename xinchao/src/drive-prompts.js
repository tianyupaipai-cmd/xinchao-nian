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
// 挑哪股：先看「此刻」里涌 / 涨的；没有就看「积」——一直在自己静息线七成以上待满 1.5 小时（刚被满足、在饱足平台上的不算）。

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
export function pickDrivePrompt(state, record, prompts, now = new Date(), { timeZone = 'Asia/Shanghai' } = {}) {
  const nowMs = now.getTime();
  const { day, hour } = localDayAndHour(now, timeZone);
  let rec = record && record.day === day ? { ...record, last: { ...(record.last ?? {}) } } : { day, count: 0, night: 0, last: {}, lastAt: record?.lastAt ?? null, wakeUsed: false };
  const none = { record: rec, text: '', drive: null };
  if (!prompts) return none;
  const night = hour < NIGHT_END_HOUR;
  if (night ? rec.night >= NIGHT_MAX : rec.count - rec.night >= DAY_MAX) return none;
  const lastAt = Date.parse(rec.lastAt ?? '');
  if (Number.isFinite(lastAt) && nowMs - lastAt < MIN_GAP_MS) return none;
  const cool = (k) => nowMs - Number(rec.last[k] ?? 0) >= SAME_DRIVE_COOLDOWN_MS;

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
