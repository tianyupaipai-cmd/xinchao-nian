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
// 4.2 三件可调：
//   - 两条之间的最短间隔（DRIVE_PROMPT_MIN_GAP_MINUTES，默认 45）；
//   - 通话进行中先压着：照常挑，但不递，记进 callHeld；挂断后补一条汇总（不占间隔、不受条数上限）。
//     通话状态由宿主经 POST /v1/call { active } 告诉心潮，存在 call-state.json；通话中宿主每隔几分钟核一次连接还在就再报一次 active（刷新 refreshedAt），
//     超过 3 小时没刷新才按失联清理——整夜开着电话睡也不会被兜底提前当成挂断；
//     开了睡觉模式就放行：通话开着睡觉模式（宿主 POST /v1/call { sleep: true }）时不压，照常递；
//     开睡觉模式前攒下的，也在下一轮先补成汇总递出去。挂断时睡觉模式标记一起清掉。
//   - 她刚来过（DRIVE_PROMPT_PRESENT_SKIP_MINUTES 分钟内有对话或通话心跳）就不提「牵挂」——人就在跟前，不用去找她。
// 4.3「攒着」（借了 Kirie 的思路：立刻说 / 攒着晚点一起说 / 不说，发出去之前再核一遍——github.com/khaterdev/kirie，MIT）：
//   通话里压着、挂断补汇总（上面那条）推广成通用的「攒着」，话术文件里配（不配就只有通话那一种，和以前一样）：
//     "stash":     ["分享欲", "好奇", "野心", "愤怒"]   // 可以攒：碰上不合适的时候先记下来，晚点一起说
//     "immediate": ["牵挂", "偏爱"]                     // 立刻：从不攒，通话中也照常递（攒着就变味了）
//     "bedtimeHour": 23                                  // 睡前：几点起把攒着的放出来（可选，默认 23）
//   什么时候攒（每条记原因）：通话中（没配 stash 的驱力也照旧攒）；她在忙（宿主传 busy）；刚说过（两条间隔没到、这股正涌/涨）。
//   什么时候放：挂断（或开了睡觉模式）、她来了（离开至少半小时后回来说话）、睡前（每天到点放一次）；放的时候不看间隔和条数上限，合成一条。
//   放之前每条再核一遍：还在涌/涨、或还在静息线七成以上才说；已经落下去的（被满足了、气消了）不提，全落了就整条不发。
//   攒了 18 小时还没放出来的自动作废。

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
const STASH_STALE_MS = 18 * H;              // 攒了这么久还没放出来就作废
const STASH_BACK_MS = 15 * 60_000;          // 「她来了」：她回来说话就在这一刻钟里
const AWAY_MS = 30 * 60_000;                // 离开至少这么久再来说话，才算「她来了」（一直在聊不算，不然「刚说过」攒下的下一轮就放，间隔形同虚设）
const BEDTIME_HOUR = 23;
const REASON_LABEL = { 通话中: '通话时', 她在忙: '她忙的时候', 刚说过: '刚说过话时' };
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
  const keys = (list) => (Array.isArray(list) ? list : []).map(resolveKey).filter(Boolean);
  const bed = Number(raw?.bedtimeHour);
  return {
    hints,
    held,
    stash: keys(raw?.stash),
    immediate: keys(raw?.immediate),
    bedtimeHour: Number.isInteger(bed) && bed >= 0 && bed <= 23 ? bed : BEDTIME_HOUR,
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

// 放出来之前再核一遍：还在涌/涨、或还在静息线七成以上；刚被满足（饱足平台上）的不算
function stillHigh(state, key, now) {
  const nowMs = now.getTime();
  const until = Date.parse(state?.satisfactionPlateaus?.[key]?.until ?? '');
  if (Number.isFinite(until) && until > nowMs) return false;
  const v = Number(state?.drives?.[key] ?? 0);
  const lv = driveLevel(key, v, driveTrend(state, key, now));
  if (lv === '涌' || lv === '涨') return true;
  if (lv === '落') return false;
  return v >= HELD_RATIO * Number(DIMENSIONS[key]?.ceil ?? 0.5);
}

/**
 * 纯函数：给定心潮状态、上次的提示记录和话术，决定这一轮要不要提、提哪股。
 * 返回 { record, text, drive }；不提时 text 为空（record 可能因跨天重置而变）。
 */
export function pickDrivePrompt(state, record, prompts, now = new Date(), { timeZone = 'Asia/Shanghai', dayMax = DAY_MAX, nightMax = NIGHT_MAX, nightSkipChatMinutes = 0, minGapMinutes = MIN_GAP_MS / 60_000, presentSkipMinutes = 0, call = null, busy = '' } = {}) {
  const nowMs = now.getTime();
  const { day, hour } = localDayAndHour(now, timeZone);
  let rec = record && record.day === day ? { ...record, last: { ...(record.last ?? {}) } } : { day, count: 0, night: 0, last: {}, lastAt: record?.lastAt ?? null, wakeUsed: false };
  // 攒着的跨天也不丢；10-29 以前的记录叫 callHeld（只有通话一种），并进来记成「通话中」
  const oldCall = Array.isArray(record?.callHeld) ? record.callHeld.map((h) => ({ key: h.key, tag: h.tag, reason: '通话中', at: h.at ?? record?.lastAt ?? iso(now) })) : [];
  rec.stash = [...(Array.isArray(record?.stash) ? record.stash : []), ...oldCall].filter((h) => nowMs - (Date.parse(h.at ?? '') || nowMs) < STASH_STALE_MS);
  delete rec.callHeld;
  const none = { record: rec, text: '', drive: null };
  if (!prompts) return none;
  const stashable = new Set(prompts.stash ?? []);
  const immediate = new Set(prompts.immediate ?? []);
  const night = hour < NIGHT_END_HOUR;
  const callSeen = Math.max(Date.parse(call?.since ?? '') || 0, Date.parse(call?.refreshedAt ?? '') || 0);
  const inCall = Boolean(call?.active) && callSeen > 0 && nowMs - callSeen < CALL_STALE_MS;
  const holding = inCall && call?.sleep !== true;   // 10-24：睡觉模式开着就不压
  const lastTalk = Date.parse(state?.lastConversationAt ?? '');
  // 她来了：上一轮看到的「最后一次说话」和这一轮的隔了半小时以上 → 她离开过又回来了。每轮记下这一轮看到的
  const prevTalk = Date.parse(rec.talkSeen ?? '');
  const cameBack = Number.isFinite(lastTalk) && nowMs - lastTalk < STASH_BACK_MS && Number.isFinite(prevTalk) && lastTalk - prevTalk >= AWAY_MS;
  if (Number.isFinite(lastTalk)) rec.talkSeen = iso(lastTalk);

  // 放出来：挂断（或开了睡觉模式）/ 她来了 / 睡前。合成一条，不看间隔和条数上限；放之前每条核一遍
  if (!holding && rec.stash.length) {
    const hungUp = rec.stash.some((h) => h.reason === '通话中');
    const herBack = cameBack && rec.stash.some((h) => lastTalk > (Date.parse(h.at ?? '') || 0));
    const bedtime = !night && hour >= (prompts.bedtimeHour ?? BEDTIME_HOUR) && rec.bedDay !== day;   // 睡前：每天到点放一次
    if (hungUp || herBack || bedtime) {
      const keep = rec.stash.filter((h) => stillHigh(state, h.key, now));
      const dropped = rec.stash.filter((h) => !keep.includes(h)).map((h) => h.key);
      rec = { ...rec, stash: [], ...(bedtime ? { bedDay: day } : {}) };
      if (!keep.length) return { record: rec, text: '', drive: null, released: [], dropped };
      rec = { ...rec, count: rec.count + 1, night: rec.night + (night ? 1 : 0), lastAt: iso(now) };
      const moment = hungUp ? (call?.sleep === true && call?.active ? '开了睡觉模式' : '挂断了') : herBack ? '她来了' : '要睡了';
      const groups = Object.entries(keep.reduce((g, h) => ({ ...g, [h.reason]: [...(g[h.reason] ?? []), h] }), {}))
        .map(([reason, hs]) => `${REASON_LABEL[reason] ?? reason}攒下：${hs.map((h) => `${DRIVE_SHORT[h.key] ?? h.key}（${h.tag}）`).join('、')}`);
      const lines = ['驱力提示', `· ${moment}，${groups.join('；')}`];
      const firstHint = prompts.hints[keep[keep.length - 1].key];
      if (firstHint) lines.push(`· ${firstHint}`);
      if (prompts.footer) lines.push(prompts.footer.replace('{n}', String(rec.count)));
      return { record: rec, text: lines.join('\n'), drive: keep[keep.length - 1].key, summary: true, released: keep.map((h) => h.key), dropped };
    }
  }

  if (!night && hour >= (prompts.bedtimeHour ?? BEDTIME_HOUR) && rec.bedDay !== day && !holding) rec.bedDay = day;   // 到点时没东西可放，也算这天的睡前过了
  if (night ? (nightMax > 0 && rec.night >= nightMax) : (dayMax > 0 && rec.count - rec.night >= dayMax)) return none;
  if (night && nightSkipChatMinutes > 0 && Number.isFinite(lastTalk) && nowMs - lastTalk < nightSkipChatMinutes * 60_000) return none;
  const lastAt = Date.parse(rec.lastAt ?? '');
  const gapBlocked = Number.isFinite(lastAt) && nowMs - lastAt < Math.max(1, Number(minGapMinutes) || 45) * 60_000;
  if (gapBlocked && !stashable.size) return none;
  const present = presentSkipMinutes > 0 && Number.isFinite(lastTalk) && nowMs - lastTalk < presentSkipMinutes * 60_000;
  const stashed = new Set(rec.stash.map((h) => h.key));
  const cool = (k) => nowMs - Number(rec.last[k] ?? 0) >= SAME_DRIVE_COOLDOWN_MS && !(present && PRESENT_SKIP.has(k)) && !stashed.has(k);

  let pick = null;
  for (const d of shownDrives(state)) {
    if (!prompts.hints[d.key] || !cool(d.key)) continue;
    if (gapBlocked && !stashable.has(d.key)) continue;   // 刚说过：只看能攒的那几股
    const v = Number(d.value);
    const lv = driveLevel(d.key, v, driveTrend(state, d.key, now));
    if (lv !== '涌' && lv !== '涨') continue;
    if (d.key === 'reflection' && lv === '涌' && v < Number(DIMENSIONS.reflection.ceil) + REFLECTION_SURGE_MARGIN) continue;
    pick = { key: d.key, tag: lv };
    break;
  }
  const stash = (reason, touchGap) => ({
    record: { ...rec, stash: [...rec.stash, { key: pick.key, tag: pick.tag, reason, at: iso(now) }], ...(touchGap ? { lastAt: iso(now) } : {}), last: { ...rec.last, [pick.key]: nowMs } },
    text: '', drive: null, held: pick.key, reason,
  });
  // 刚说过（间隔没到）：正涌/涨的、能攒的那股先记下来；「积」着的不用攒，它一直在，过了间隔自然会提
  if (gapBlocked) return pick ? stash('刚说过', false) : none;
  if (!pick) {
    const cands = prompts.held
      .filter((k) => prompts.hints[k] && cool(k))
      .map((k) => ({ key: k, hours: heldHours(state, k, nowMs) }))
      .filter((c) => c.hours > 0)
      .sort((a, b) => Number(rec.last[a.key] ?? 0) - Number(rec.last[b.key] ?? 0) || b.hours - a.hours);   // 轮流：最久没提过的先
    if (cands.length) pick = { key: cands[0].key, tag: `积·${cands[0].hours >= 23 ? '一整天' : `${Math.max(2, Math.round(cands[0].hours))} 小时`}` };
  }
  if (!pick) return none;
  if (!immediate.has(pick.key)) {
    // 通话进行中：不递，记下来；照样占这一股的冷却和间隔，免得挂断时攒一长串（没配 stash 的驱力也照旧这样）
    if (holding) return stash('通话中', true);
    if (busy && stashable.has(pick.key)) return stash('她在忙', true);
  }

  rec = { ...rec, count: rec.count + 1, night: rec.night + (night ? 1 : 0), lastAt: iso(now), last: { ...rec.last, [pick.key]: nowMs } };
  const wake = night && prompts.wake?.drive === pick.key && !rec.wakeUsed;
  if (wake) rec.wakeUsed = true;
  const lines = ['驱力提示', `· ${DRIVE_SHORT[pick.key] ?? pick.key}（${pick.tag}）：${prompts.hints[pick.key]}`];
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
