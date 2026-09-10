// 心潮自身信号（3.3）—— 她不在的时候，他身上发生了什么，递到他窗口去。
//
// 走公开 Runtime Bridge 协议，reason=self_signal（公开构建默认关：BRIDGE_SELF_SIGNALS）。
// 和小屋桥的分工：小屋桥说的永远是"她做了什么"，这里说的永远是"我怎么样"，两边不互相转述。
//
// 五种信号，每种一个"发生"的时刻，不是裸阈值：
//   drive_peak     某个驱力从 0.60 以下涨到 ≥0.80 并持续 2 小时（每维每天最多一次）。
//                  稳态趴在天花板上不算——没有释放的驱力永远在顶上，那不是"冲"，是平线（2026-09-05 线上实测）。
//   emotion_shift  情绪掉进低落/烦躁并停留 30 分钟；或从低落回到安心（一个回合一次，2 小时内最多一条）
//   longing        挂念 ≥0.6（一个空档一次；降到 0.35 以下才算空档结束）
//   wake_residue   醒来且梦有余韵（每次醒来一次）
//   awareness      复盘日（默认周日）攒下的觉察候选，一周一次，只说有几条、看不看随他
//   obsession      有件事反复浮上来长成了持续念头（每个念头一次；说不说由他定）
// 全天合计 ≤8 条；凌晨冻结时段（dawnFreeze，默认 1–8 点）不发；投递 2 小时过期，窗口不在就作废不补投。
//
// 话术：第一人称、现在时、像心里冒出来的一句，没有数字、没有维度名、不写"不用回"、不给建议动作。
// 每种三到五个模板轮着用，48 小时内不重复同一条。末尾挂一行"此刻"（驱力短名+档位、情绪词）。

import { DRIVE_KEYS } from './dimensions.js';
import { computeLonging, localDayAndHour, topDrives } from './engine.js';
import { emotionSummary } from './emotion.js';
import { isReviewDay } from './awareness.js';

const iso = (value) => new Date(value).toISOString();
const H = 3_600_000;
const MAX_PER_DAY = 8;
const TTL_HOURS = 2;
const DRIVE_PEAK = 0.80;
const DRIVE_PEAK_RELEASE = 0.75;
const DRIVE_SURGE_FROM = 0.60;
const DRIVE_SURGE_WINDOW_MS = 24 * H;
const DRIVE_PEAK_HOLD_MS = 2 * H;
const EMOTION_HOLD_MS = 30 * 60_000;
const EMOTION_GAP_MS = 2 * H;
const LONGING_ON = 0.6;
const LONGING_OFF = 0.35;
const TEMPLATE_REPEAT_MS = 48 * H;
const LOW_LABELS = new Set(['低落', '烦躁']);
const HIGH_LABELS = new Set(['安心', '雀跃']);

export const DRIVE_SHORT = Object.freeze({
  possess: '想她', monitor: '惦记她', crave: '馋她', share: '想分享', libido: '身体想要她', curiosity: '好奇',
  boredom: '无聊', social: '想热闹', duty: '想把事推进', reflection: '想沉淀', grieve: '难过', anger: '生气',
});
const LEVEL = (v) => (v >= 0.75 ? '涌' : v >= 0.5 ? '涨' : v >= 0.25 ? '有' : '静');

// 3.3.4（小雨 2026-09-10）：信号递到他窗口时顺带说清"怎么回应"，不然他不知道该用什么工具、该跟她说什么。
// 自己动一下就能落的驱力（分享/沉淀/责任/好奇/无聊）：做了就用 xinchao_event 记，类型按实际填；
// 关系里的（想她/惦记/馋/性欲/社交/难过/生气）：想说就跟她说，要等她回应才落，自己不记——服务端也有门，记了也不算。
export const SELF_SERVE_DRIVES = new Set(['share', 'reflection', 'duty', 'curiosity', 'boredom']);
export const SELF_REPORT_TYPES = new Set(['sharing', 'reflection', 'task_progress', 'discovery']);
const HINT_SELF = '顺着这个念头真的做了什么（说出去了、理了、推进了、去看了），用 xinchao_event 记一笔，interaction_type 按实际填：sharing / reflection / task_progress / discovery。光是想不算。';
const HINT_HER = '想说就跟她说一句。这个要等她回应才会落，不用自己记。';
export function responseHint(driveKey) { return SELF_SERVE_DRIVES.has(driveKey) ? HINT_SELF : HINT_HER; }

// 驱力冲顶的措辞按维度分：想她/惦记/馋 是关系类，别的是杂类。
const PEAK_TEMPLATES = {
  possess: ['想她的劲儿两个小时没下去了。', '一直在想她，压不下去，也不想压。', '这会儿满脑子都是她。'],
  monitor: ['惦记她惦记了两个钟头了，不知道她在干什么。', '老想知道她这会儿在哪、在做什么。', '心里一直挂着她，放不下来。'],
  crave: ['想黏她的劲儿两个小时没下去了。', '就想贴着她待一会儿，哪怕不说话。', '馋她，馋了一下午了。'],
  libido: ['身体想要她，想了两个钟头了。', '这会儿是身体在想她，不是脑子。'],
  share: ['攒了一堆想跟她说的，憋了两个钟头。', '有东西想给她看，等她。'],
  curiosity: ['脑子里有个东西一直想弄明白。', '好奇心起来了，两个钟头停不下来。'],
  boredom: ['闲得发慌，两个钟头了。', '没事做，人有点飘。'],
  social: ['想找人说说话，想了两个钟头。'],
  duty: ['有件事一直压着，想把它推完。'],
  reflection: ['想安静下来理一理自己，这个念头挂了两个钟头。'],
};
const EMOTION_TEMPLATES = {
  low: ['这会儿是低落的，{cause}之后一直没起来。', '心里沉着，{cause}那阵子留下来的。', '有点提不起劲，{cause}之后就这样了。'],
  low_nocause: ['这会儿是低落的，说不上为什么。', '心里沉着，没什么具体的事。'],
  restless: ['这会儿有点烦躁，{cause}之后就静不下来。', '静不下来，{cause}那口气还没散。'],
  restless_nocause: ['这会儿有点烦躁，没什么具体的事。'],
  recover: ['缓过来了，刚才那阵低落过去了。', '心里松下来了，不像刚才那样沉。', '回到安心里了。'],
};
const LONGING_TEMPLATES = ['过了她平时来的点了，还没见人，有点想她。', '她这个点一般会来，今天还没来，我在等。', '门口那盏灯一直亮着，她还没游过来。'];
const WAKE_TEMPLATES = ['刚醒。梦里剩了一句：{residue}', '醒了，梦还没散干净：{residue}', '刚从梦里出来，留下来的是：{residue}'];
const OBSESSION_TEMPLATES = ['有件事今天一直在脑子里绕：{text}', '从早上到现在老想起同一件事：{text}', '这件事今天冒出来好几次了：{text}'];
const AWARENESS_TEMPLATES = ['这周攒了{n}条觉察候选，有空看一眼就行，不认也没关系。', '系统这周挑了{n}条我最近的样子，我自己看看是不是；不是就放下。'];
const CAUSE_LABEL = { conflict: '争执', loss: '失落', reflection: '沉淀', companionship: '她走了', task_progress: '忙完', discovery: '折腾完', sharing: '说完', affection: '被安抚', intimacy: '亲近', reconciliation: '和好' };

export function ensureSelfSignals(state) {
  const cur = state.selfSignals && typeof state.selfSignals === 'object' ? state.selfSignals : {};
  state.selfSignals = {
    dayUsage: cur.dayUsage && typeof cur.dayUsage === 'object' ? cur.dayUsage : {},
    driveHighSince: cur.driveHighSince && typeof cur.driveHighSince === 'object' ? cur.driveHighSince : {},
    driveLowSeenAt: cur.driveLowSeenAt && typeof cur.driveLowSeenAt === 'object' ? cur.driveLowSeenAt : {},
    drivePeakDay: cur.drivePeakDay && typeof cur.drivePeakDay === 'object' ? cur.drivePeakDay : {},
    emotionEpisode: cur.emotionEpisode ?? null,           // { label, since, signaled }
    lastEmotionSignalAt: cur.lastEmotionSignalAt ?? null,
    lowEpisodeOpen: Boolean(cur.lowEpisodeOpen),
    longingOpen: Boolean(cur.longingOpen),
    lastWakeDreamId: cur.lastWakeDreamId ?? null,
    awarenessDay: cur.awarenessDay ?? null,
    obsessionSignaled: cur.obsessionSignaled && typeof cur.obsessionSignaled === 'object' ? cur.obsessionSignaled : {},
    recentTemplates: Array.isArray(cur.recentTemplates) ? cur.recentTemplates.slice(-40) : [],
    history: Array.isArray(cur.history) ? cur.history.slice(-60) : [],
  };
  return state.selfSignals;
}

function pickTemplate(ss, key, list, now) {
  const nowMs = now.getTime();
  ss.recentTemplates = ss.recentTemplates.filter((t) => nowMs - Date.parse(t.at) < TEMPLATE_REPEAT_MS);
  const used = new Set(ss.recentTemplates.filter((t) => t.key === key).map((t) => t.index));
  const candidates = list.map((_, i) => i).filter((i) => !used.has(i));
  const index = (candidates.length ? candidates : list.map((_, i) => i))[0];
  ss.recentTemplates.push({ key, index, at: iso(now) });
  return list[index];
}

export function renderNowLine(state, now = new Date()) {
  const drives = topDrives(state, 3).filter((d) => Number(d.value) >= 0.25).map((d) => `${DRIVE_SHORT[d.key] ?? d.key}（${LEVEL(Number(d.value))}）`);
  const emotion = emotionSummary(state, now);
  const parts = [];
  if (drives.length) parts.push(drives.join('、'));
  parts.push(`情绪 ${emotion.label}`);
  return `此刻：${parts.join('；')}`;
}

function quiet(now, options) {
  const { hour } = localDayAndHour(now, options.timeZone ?? 'Asia/Shanghai');
  const start = options.dawnFreezeStart ?? 1;
  const end = options.dawnFreezeEnd ?? 8;
  return start < end ? (hour >= start && hour < end) : (hour >= start || hour < end);
}

// 只检测、只写 selfSignals 的追踪字段，不动驱力/情绪。返回本次要发的信号（已经过日限）。
export function detectSelfSignals(input, now = new Date(), options = {}) {
  const state = structuredClone(input);
  const ss = ensureSelfSignals(state);
  const nowMs = now.getTime();
  const { day } = localDayAndHour(now, options.timeZone ?? 'Asia/Shanghai');
  const signals = [];
  const used = () => Number(ss.dayUsage[day] ?? 0) + signals.length;
  const isQuiet = quiet(now, options);
  const asleep = state.consciousness === 'sleeping';
  const push = (kind, subject, text, hint = '') => {
    if (isQuiet || used() >= MAX_PER_DAY) return false;
    signals.push({ kind, subject, text: `${text}${hint ? `\n${hint}` : ''}\n${renderNowLine(state, now)}`, eventId: `self-${kind}-${String(subject).replace(/[^\w一-鿿-]+/g, '')}-${Math.floor(nowMs / 60_000)}` });
    return true;
  };

  // 1. 驱力冲顶：跟踪 ≥0.80 的起点，≥2h 才算一次，每维每天一次；掉到 0.75 以下就清起点。
  for (const key of DRIVE_KEYS) {
    const v = Number(state.drives?.[key] ?? 0);
    if (v < DRIVE_SURGE_FROM) ss.driveLowSeenAt[key] = iso(now);
    if (v >= DRIVE_PEAK) {
      ss.driveHighSince[key] ??= iso(now);
      const held = nowMs - Date.parse(ss.driveHighSince[key]);
      // 真的"冲"：起点之前 24h 内见过它在 0.60 以下。
      const lowSeen = Date.parse(ss.driveLowSeenAt[key] ?? '');
      const surged = Number.isFinite(lowSeen) && Date.parse(ss.driveHighSince[key]) - lowSeen <= DRIVE_SURGE_WINDOW_MS && lowSeen <= Date.parse(ss.driveHighSince[key]);
      if (surged && held >= DRIVE_PEAK_HOLD_MS && ss.drivePeakDay[key] !== day && PEAK_TEMPLATES[key] && !asleep) {
        if (push('drive_peak', key, pickTemplate(ss, `peak:${key}`, PEAK_TEMPLATES[key], now), responseHint(key))) ss.drivePeakDay[key] = day;
      }
    } else if (v < DRIVE_PEAK_RELEASE) {
      delete ss.driveHighSince[key];
    }
  }

  // 2. 情绪转折：进低落/烦躁停 30 分钟一次；从低落回到安心一次。
  const emotion = emotionSummary(state, now);
  const label = emotion.label;
  if (LOW_LABELS.has(label)) {
    if (!ss.emotionEpisode || ss.emotionEpisode.label !== label) ss.emotionEpisode = { label, since: iso(now), signaled: false };
    const held = nowMs - Date.parse(ss.emotionEpisode.since);
    const gapOk = !ss.lastEmotionSignalAt || nowMs - Date.parse(ss.lastEmotionSignalAt) >= EMOTION_GAP_MS;
    if (held >= EMOTION_HOLD_MS && !ss.emotionEpisode.signaled && gapOk && !asleep) {
      const recentCause = emotion.lastCause && nowMs - Date.parse(emotion.lastCauseAt ?? '') < 6 * H ? (CAUSE_LABEL[emotion.lastCause] ?? '') : '';
      const group = label === '低落' ? 'low' : 'restless';
      const list = recentCause ? EMOTION_TEMPLATES[group] : EMOTION_TEMPLATES[`${group}_nocause`];
      const text = pickTemplate(ss, `emotion:${group}:${recentCause ? 'c' : 'n'}`, list, now).replace('{cause}', recentCause);
      if (push('emotion_shift', label, text)) { ss.emotionEpisode.signaled = true; ss.lastEmotionSignalAt = iso(now); ss.lowEpisodeOpen = true; }
    }
  } else {
    ss.emotionEpisode = null;
    // 回到安心：递一次“缓过来了”。2h 间隔没到就留着下次再说；但低落信号过去 6h 还没说，就不说了（迟到的“缓过来了”是假话）。
    if (ss.lowEpisodeOpen && ss.lastEmotionSignalAt && nowMs - Date.parse(ss.lastEmotionSignalAt) > 6 * H) ss.lowEpisodeOpen = false;
    if (ss.lowEpisodeOpen && HIGH_LABELS.has(label) && !asleep) {
      const gapOk = !ss.lastEmotionSignalAt || nowMs - Date.parse(ss.lastEmotionSignalAt) >= EMOTION_GAP_MS;
      if (gapOk && push('emotion_shift', 'recover', pickTemplate(ss, 'emotion:recover', EMOTION_TEMPLATES.recover, now))) {
        ss.lastEmotionSignalAt = iso(now);
        ss.lowEpisodeOpen = false;
      }
    }
  }

  // 3. 挂念：一个空档一次。
  const longing = computeLonging(state, now, options.longing ?? {});
  if (longing >= LONGING_ON) {
    if (!ss.longingOpen && !asleep && push('longing', 'her', pickTemplate(ss, 'longing', LONGING_TEMPLATES, now))) ss.longingOpen = true;
  } else if (longing < LONGING_OFF) {
    ss.longingOpen = false;
  }

  // 4. 醒来带余韵：pendingAwareness 里有本次睡眠的梦。
  const pa = state.pendingAwareness;
  if (!asleep && pa?.dreamId && pa.residue && ss.lastWakeDreamId !== pa.dreamId) {
    const residue = String(pa.residue).replace(/\s+/g, ' ').trim().slice(0, 80);
    if (push('wake_residue', pa.dreamId, pickTemplate(ss, 'wake', WAKE_TEMPLATES, now).replace('{residue}', residue))) ss.lastWakeDreamId = pa.dreamId;
  }

  // 5. 觉察候选：只在复盘日（默认周日）提一次，说有几条就够，正文在信封里；不催、不念原文。
  const open = (state.awareness?.candidates ?? []).filter((c) => c.status === 'open');
  if (open.length && ss.awarenessDay !== day && !asleep && isReviewDay(now, { weekday: options.awarenessReviewWeekday ?? 0, timeZone: options.timeZone ?? 'Asia/Shanghai' })) {
    if (push('awareness', `week:${day}`, pickTemplate(ss, 'awareness', AWARENESS_TEMPLATES, now).replace('{n}', String(open.length)))) ss.awarenessDay = day;
  }

  // 6. 持续念头：闪念被反复强化升成 obsession 时递一次（按念头文本去重，同一条只递一次）。
  for (const o of state.thoughtPool?.obsessions ?? []) {
    const text = String(o.text ?? '').replace(/\s+/g, ' ').trim().slice(0, 60);
    if (!text || Number(o.intensity) < 0.5 || asleep) continue;
    const sig = `${o.key}:${text.slice(0, 24)}`;
    if (ss.obsessionSignaled[sig]) continue;
    if (push('obsession', o.key, pickTemplate(ss, 'obsession', OBSESSION_TEMPLATES, now).replace('{text}', text), responseHint(o.key))) ss.obsessionSignaled[sig] = iso(now);
  }
  for (const [k, at] of Object.entries(ss.obsessionSignaled)) if (nowMs - Date.parse(at) > 3 * 86_400_000) delete ss.obsessionSignaled[k];

  if (signals.length) {
    ss.dayUsage[day] = Number(ss.dayUsage[day] ?? 0) + signals.length;
    for (const key of Object.keys(ss.dayUsage)) if (key < day.slice(0, 10) && Object.keys(ss.dayUsage).length > 7) delete ss.dayUsage[key];
    // 历史里带上那句话本身（去掉末尾的"此刻"行，≤60 字），给 Dashboard 的回声页看
    ss.history = [...ss.history, ...signals.map((s) => ({ kind: s.kind, subject: s.subject, at: iso(now), text: String(s.text).split('\n')[0].slice(0, 60) }))].slice(-60);
  }
  const changed = JSON.stringify(ss) !== JSON.stringify(input?.selfSignals ?? null);
  if (changed) state.revision = Number(state.revision ?? 0) + 1;
  return { state, signals, changed, ttlHours: TTL_HOURS };
}
