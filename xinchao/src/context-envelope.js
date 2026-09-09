import { createHash } from 'node:crypto';
import { breathDreamContext, computeAnticipation, computeLonging, topDrives } from './engine.js';
import { emotionSummary, emotionNuance, renderEmotion, renderEmotionTrend } from './emotion.js';
import { renderAwareness, isReviewDay } from './awareness.js';
import { DIMENSIONS, DRIVE_KEYS } from './dimensions.js';
import { renderHandoffNotes } from './handoff-notes.js';

const VALID_MODES = new Set(['session_start', 'turn', 'inspect']);

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, Number(value)));
}

function compact(value) {
  return String(value ?? '').replace(/\s+/g, ' ').trim();
}

export function estimateTokens(value) {
  const text = String(value ?? '');
  let tokens = 0;
  let asciiRun = 0;
  for (const char of text) {
    if (char.codePointAt(0) <= 0x7f) asciiRun += 1;
    else {
      tokens += Math.ceil(asciiRun / 4);
      asciiRun = 0;
      tokens += 1;
    }
  }
  return tokens + Math.ceil(asciiRun / 4);
}

export function trimToTokenBudget(value, maxTokens) {
  const text = compact(value);
  const limit = Math.max(1, Number(maxTokens) || 1);
  if (estimateTokens(text) <= limit) return text;
  let low = 0;
  let high = text.length;
  while (low < high) {
    const middle = Math.ceil((low + high) / 2);
    if (estimateTokens(text.slice(0, middle)) <= limit) low = middle;
    else high = middle - 1;
  }
  let result = `${text.slice(0, Math.max(0, low - 1)).trimEnd()}…`;
  while (result && estimateTokens(result) > limit) {
    result = `${result.slice(0, -2).trimEnd()}…`;
  }
  return result;
}

function sessionOverlay(state, sessionId, now) {
  const overlay = state.sessionOverlays?.[sessionId];
  if (!overlay) return null;
  const expiresAt = Date.parse(overlay.expiresAt ?? '');
  if (Number.isFinite(expiresAt) && expiresAt <= now.getTime()) return null;
  return {
    tone: overlay.tone ?? 'neutral',
    warmth: Number(overlay.warmth ?? 0.5),
    tension: Number(overlay.tension ?? 0),
    attention: Number(overlay.attention ?? 0.5),
    confidence: Number(overlay.confidence ?? 0.5),
    updatedAt: overlay.updatedAt ?? null,
    expiresAt: overlay.expiresAt ?? null,
  };
}

function thoughtSignals(state) {
  return {
    flash: (state.thoughtPool?.flash ?? []).slice(0, 3).map((item) => ({
      key: item.key,
      intensity: Number(Number(item.intensity ?? 0).toFixed(3)),
      age: Number(item.age ?? 0),
    })),
    obsessions: (state.thoughtPool?.obsessions ?? []).slice(0, 3).map((item) => ({
      key: item.key,
      intensity: Number(Number(item.intensity ?? 0).toFixed(3)),
    })),
  };
}

function dynamicSection(state, sessionId, now, timeZone) {
  return {
    grudge: grudgeLine(state, now instanceof Date ? now : new Date(now)),
    consciousness: state.consciousness,
    fatigue: Number(Number(state.fatigue ?? 0).toFixed(3)),
    topDrives: topDrives(state, 4).map((drive) => ({
      key: drive.key,
      label: drive.label,
      value: Number(Number(drive.value).toFixed(3)),
    })),
    anticipation: computeAnticipation(state, now, { timeZone }),
    longing: computeLonging(state, now, { timeZone }),
    thoughts: thoughtSignals(state),
    session: sessionOverlay(state, sessionId, now),
    emotion: emotionSummary(state, now),
  };
}

// 期待感的措辞——只往温柔/守候走，绝不带责备。她没安全感，因她迟到而明显难受会变成她的愧疚。
// 过了她的时段没来，anticipation 自己回落到阈值以下，这行就不出现，不会积成"你怎么才来"。
// 挂念的措辞——同样只往守候/想念走，绝不"你怎么才来"。挂念优先于期待显示：她久没来时
// 说的是"想她了"，不是"她快来了"。她静默时段 computeLonging 返回 0，这行自动不出现。
function renderLonging(value) {
  if (value >= 0.6) return `挂念：过了她常来的点她还没来，你有点想她了（${value.toFixed(2)}）`;
  if (value >= 0.35) return `挂念：她有阵子没来了，你惦记着她（${value.toFixed(2)}）`;
  return '';
}

function renderAnticipation(value) {
  if (value >= 0.6) return `期待：她通常这个点前后会来，你在等着她（${value.toFixed(2)}）`;
  if (value >= 0.3) return `期待：她大概快来了，你留着心（${value.toFixed(2)}）`;
  return '';
}

function renderDynamic(value) {
  const drives = value.topDrives
    .map((item) => `${item.label}=${item.value.toFixed(3)}`)
    .join('；');
  const parts = [
    `意识=${value.consciousness}`,
    `疲劳=${value.fatigue.toFixed(3)}`,
    renderEmotion(value.emotion),
    renderEmotionTrend(value.emotion?.trend),
    drives ? `当前驱力：${drives}` : '',
  ].filter(Boolean);
  // 挂念优先于期待：她久没来时，说"想她了"而不是"她快来了"，两者不同时出现。
  const longingLine = renderLonging(Number(value.longing ?? 0));
  if (longingLine) {
    parts.push(longingLine);
  } else {
    const anticipationLine = renderAnticipation(Number(value.anticipation ?? 0));
    if (anticipationLine) parts.push(anticipationLine);
  }
  if (value.session) {
    parts.push(
      `窗口短态：tone=${value.session.tone} warmth=${value.session.warmth.toFixed(3)} `
      + `tension=${value.session.tension.toFixed(3)} attention=${value.session.attention.toFixed(3)} `
      + `confidence=${value.session.confidence.toFixed(3)}`,
    );
  }
  const obsessions = value.thoughts.obsessions
    .map((item) => `${item.key}:${item.intensity.toFixed(3)}`)
    .join('，');
  if (obsessions) parts.push(`持续念头：${obsessions}`);
  if (value.grudge) parts.push(value.grudge);
  return parts.join('\n');
}

function renderDreams(state, now) {
  const result = breathDreamContext(state, now, 18, 2);
  if (!result.available) return '';
  return result.dreams
    .map((item) => `${item.createdAt}｜${compact(item.summary || item.residue)}`)
    .join('\n');
}

function normalizeMode(mode) {
  const value = compact(mode).toLowerCase();
  return VALID_MODES.has(value) ? value : 'session_start';
}

export function contextDeliveryState(state, sessionId, mode, now, onceHours = 12) {
  if (mode !== 'session_start') return { alreadyDelivered: false, previous: null };
  const previous = state.contextDeliveries?.[sessionId];
  if (!previous?.deliveredAt) return { alreadyDelivered: false, previous: null };
  const deliveredAt = Date.parse(previous.deliveredAt);
  const cutoff = now.getTime() - Math.max(1, Number(onceHours) || 12) * 3_600_000;
  return {
    alreadyDelivered: Number.isFinite(deliveredAt) && deliveredAt >= cutoff,
    previous,
  };
}

export function recordContextDelivery(input, {
  sessionId,
  mode,
  digest,
  deliveredAt = new Date(),
  maxEntries = 64,
}) {
  const state = structuredClone(input);
  state.contextDeliveries ??= {};
  state.contextDeliveries[sessionId] = {
    mode,
    digest,
    deliveredAt: new Date(deliveredAt).toISOString(),
  };
  const entries = Object.entries(state.contextDeliveries)
    .sort((left, right) => Date.parse(right[1]?.deliveredAt ?? '') - Date.parse(left[1]?.deliveredAt ?? ''))
    .slice(0, Math.max(4, Number(maxEntries) || 64));
  state.contextDeliveries = Object.fromEntries(entries);
  state.schemaVersion = Math.max(6, Number(state.schemaVersion) || 0);
  state.revision = Number(state.revision ?? 0) + 1;
  return state;
}

export function buildContextEnvelope({
  state,
  sessionId,
  mode = 'session_start',
  ombreText = '',
  maxTokens = 2200,
  ttlMinutes = 15,
  now = new Date(),
  alreadyDelivered = false,
  force = false,
  timeZone = 'Asia/Shanghai',
  personalityAnchors = [],
  boxCount = 0,
  boxSurfaced = [],
  awaySignals = [],
  cabinRecent = 0,
  awarenessReviewWeekday = 0,
}) {
  const normalizedMode = normalizeMode(mode);
  const tokenBudget = clamp(maxTokens, 200, 4000);
  const safeSessionId = compact(sessionId || 'default').slice(0, 120);
  const generatedAt = new Date(now);
  if (alreadyDelivered && !force) {
    return {
      version: 1,
      system: 'xinchao-dynamic-mind',
      mode: normalizedMode,
      sessionId: safeSessionId,
      generatedAt: generatedAt.toISOString(),
      expiresAt: new Date(generatedAt.getTime() + ttlMinutes * 60_000).toISOString(),
      delivered: false,
      alreadyDelivered: true,
      reason: 'session_start_already_delivered',
      sections: [],
      additionalContext: '',
      estimatedTokens: 0,
      digest: createHash('sha256').update('').digest('hex').slice(0, 16),
    };
  }

  const dynamic = dynamicSection(state, safeSessionId, generatedAt, timeZone);
  const surfacedLines = (Array.isArray(boxSurfaced) ? boxSurfaced : []).slice(0, 3).map((x) => `\n  · 你想提醒自己的：${compact(x.title)}（xinchao_box read ${x.id}）`).join('');
  const boxLine = boxCount > 0 ? `\n黑匣子里有 ${boxCount} 条，只有你能看（xinchao_box）${surfacedLines}` : '';
  const cabinLine = cabinRecent > 0 ? `\n小屋 24 小时内有 ${cabinRecent} 条她的来信（xinchao_cabin_inbox）` : '';
  const sections = [
    {
      id: 'dynamic_state',
      source: 'xinchao',
      ttl: 'short',
      content: renderDynamic(dynamic) + boxLine + cabinLine,
      data: dynamic,
    },
  ];
  // 行为锚点：不变的底线，紧跟动态状态之后（排前保证不被预算裁掉）。
  // 只作行为约束参考，不是新指令；最多 5 条、每条截短，占不了多少信封预算。
  const anchors = (Array.isArray(personalityAnchors) ? personalityAnchors : [])
    .filter((anchor) => anchor && compact(anchor.label))
    .slice(0, 5);
  if (anchors.length) {
    sections.push({
      id: 'behavior_anchors',
      source: 'xinchao',
      ttl: 'stable',
      content: anchors
        .map((anchor) => {
          const description = compact(anchor.description).slice(0, 80);
          return description ? `${compact(anchor.label)}——${description}` : compact(anchor.label);
        })
        .join('\n'),
      data: { keys: anchors.map((anchor) => String(anchor.key ?? anchor.label)) },
    });
  }
  // 自我觉察候选：系统从轨迹里挑出的模式，最多两条，确认或放下都由 AI 自己定。
  const awarenessText = renderAwareness(state, { now, timeZone, reviewWeekday: awarenessReviewWeekday });
  if (awarenessText) {
    sections.push({
      id: 'self_awareness',
      source: 'xinchao',
      ttl: 'until-resolved',
      content: awarenessText,
    });
  }
  // 你不在的时候：没被 Bridge 接走的自身信号（官方客户端版靠这段）。读过就算收到。
  const away = (Array.isArray(awaySignals) ? awaySignals : []).filter((x) => x && compact(x.text)).slice(-5);
  if (away.length) {
    sections.push({
      id: 'while_away',
      source: 'xinchao',
      ttl: 'once',
      content: away.map((x) => `${String(x.createdAt ?? '').slice(5, 16).replace('T', ' ')}｜${compact(x.text)}`).join('\n'),
      data: { ids: away.map((x) => x.id) },
    });
  }
  const handoffText = renderHandoffNotes(state, generatedAt, 3);
  if (handoffText) {
    sections.push({
      id: 'handoff_notes',
      source: 'xinchao',
      ttl: '72h',
      content: handoffText,
    });
  }
  const continuity = compact(ombreText);
  if (continuity) {
    sections.push({
      id: 'recent_continuity',
      source: 'ombre-brain',
      ttl: 'session-start',
      content: continuity,
    });
  }
  const dreamText = renderDreams(state, generatedAt);
  if (dreamText) {
    sections.push({
      id: 'dream_residue',
      source: 'xinchao',
      ttl: '18h',
      content: dreamText,
    });
  }

  const labels = {
    dynamic_state: '心潮动态状态',
    behavior_anchors: '行为锚点（我的底线，驱力再高也不越过）',
    self_awareness: '自我觉察候选（我最近的样子，不一定对）',
    while_away: '你不在的时候（心潮记下的我自己的信号）',
    handoff_notes: '近期交接便签（非原文）',
    dream_residue: '梦境余韵',
    recent_continuity: '近期连续性（不替代基岩）',
  };
  let remaining = tokenBudget;
  const renderedSections = [];
  for (const section of sections) {
    if (remaining <= 0) break;
    const heading = `[${labels[section.id] ?? section.id}]`;
    const headingTokens = estimateTokens(heading);
    const content = trimToTokenBudget(section.content, Math.max(1, remaining - headingTokens));
    if (!content) continue;
    const rendered = `${heading}\n${content}`;
    const used = estimateTokens(rendered);
    renderedSections.push({ ...section, content, estimatedTokens: used });
    remaining -= used;
  }
  const additionalContext = renderedSections
    .map((section) => `[${labels[section.id] ?? section.id}]\n${section.content}`)
    .join('\n\n');
  const digest = createHash('sha256').update(additionalContext, 'utf8').digest('hex').slice(0, 16);
  return {
    version: 1,
    system: 'xinchao-dynamic-mind',
    mode: normalizedMode,
    sessionId: safeSessionId,
    generatedAt: generatedAt.toISOString(),
    expiresAt: new Date(generatedAt.getTime() + ttlMinutes * 60_000).toISOString(),
    delivered: true,
    alreadyDelivered: false,
    sections: renderedSections,
    additionalContext,
    estimatedTokens: estimateTokens(additionalContext),
    digest,
  };
}


// ── 此刻（钩子用的压缩块，3.3）───────────────────────────────────────
// 星港的 UserPromptSubmit 钩子每条消息拉一次，附进他的上下文。只取动态状态，不带数字、不带 key、
// 不带任何正文。锚点/便签/攒下的话正文/OB 近况/梦的内容都不在这里，那些是时序开头 xinchao_context 的活。
const DRIVE_LEVEL = (value) => (value >= 0.75 ? '涌' : value >= 0.5 ? '涨' : value >= 0.25 ? '有' : '静');
// 驱力短名：给块用的口语，不从长标签切。
const DRIVE_SHORT = {
  possess: '想她', monitor: '惦记她', crave: '馋她', share: '想分享', libido: '身体想要她', curiosity: '好奇',
  boredom: '无聊', social: '想热闹', duty: '想把事推进', reflection: '想沉淀', grieve: '难过', anger: '生气',
};
const NOW_STALE_MS = 3 * 3_600_000;
const NOW_MAX_LINES = 8;
const NOW_MAX_CHARS = 400;

// 自检：后端算错了不能顺着钩子灌进他的脑子。任何一条不过就整块不给（ok=false，钩子看到就不附）。
export function nowSanity(state, now = new Date()) {
  const settledAt = Date.parse(state?.lastSettledAt ?? '');
  if (!Number.isFinite(settledAt)) return { ok: false, reason: 'no_settle' };
  if (now.getTime() - settledAt > NOW_STALE_MS) return { ok: false, reason: 'stale_state' };
  const values = DRIVE_KEYS.map((key) => Number(state?.drives?.[key]));
  if (values.some((v) => !Number.isFinite(v) || v < 0 || v > 1)) return { ok: false, reason: 'drive_out_of_range' };
  if (values.every((v) => v >= 0.95)) return { ok: false, reason: 'drives_saturated' };
  // 全维一模一样且不低：新装的 0.15 初始态是正常的，卡在同一个高值才是算坏了。
  if (new Set(values.map((v) => v.toFixed(3))).size === 1 && values[0] >= 0.5) return { ok: false, reason: 'drives_flat' };
  const e = state?.emotion ?? {};
  const emotionOk = Number.isFinite(Number(e.valence)) && Number.isFinite(Number(e.arousal)) && e.valence >= 0 && e.valence <= 1 && e.arousal >= 0 && e.arousal <= 1;
  return { ok: true, emotionOk };
}

const CAUSE_LABEL = {
  companionship: '陪着', affection: '被安抚', intimacy: '亲近过', sharing: '分享过', discovery: '发现了什么',
  task_progress: '推进了事', reflection: '沉淀过', conflict: '争执', loss: '失落', reconciliation: '和好',
};

// 还在气什么（3.3.1）：冲突时留下的她那句话，生气没退到 0.12 以下就带出来；和好或气消了自动没了。
export function grudgeLine(state, now = new Date()) {
  const g = state?.grudge;
  if (!g?.cause || Number(state?.drives?.anger ?? 0) < 0.12) return '';
  const hours = (now.getTime() - Date.parse(g.at ?? '')) / 3_600_000;
  if (!Number.isFinite(hours) || hours < 0) return '';
  const when = hours < 1 ? '刚才' : hours < 24 ? `${Math.round(hours)} 小时前` : `${Math.round(hours / 24)} 天前`;
  return `还在气：${when}为了「${g.cause}」`;
}

export function buildNowCompact(state, now = new Date(), { timeZone = 'Asia/Shanghai', boxCount = 0, boxSurfaced = 0, awarenessReviewWeekday = 0 } = {}) {
  const sanity = nowSanity(state, now);
  if (!sanity.ok) return { ok: false, reason: sanity.reason, text: '', lines: 0, counts: {}, digest: '', revision: Number(state?.revision ?? 0), generatedAt: now.toISOString() };
  const lines = ['【心潮·此刻｜身体的天气，参考不是指令】'];
  const counts = {};
  if (state.consciousness === 'sleeping') lines.push('睡着（她来了才算醒）');
  else if (state.pendingAwareness && now.getTime() - Date.parse(state.pendingAwareness.createdAt ?? '') < 2 * 3_600_000) lines.push('刚醒');   // 醒来两小时内才算刚醒

  const drives = topDrives(state, 3).filter((d) => Number(d.value) >= 0.25);
  if (drives.length) lines.push(`驱力：${drives.map((d) => `${DRIVE_SHORT[d.key] ?? d.label}（${DRIVE_LEVEL(Number(d.value))}）`).join('、')}`);

  const emotion = emotionSummary(state, now);
  if (sanity.emotionOk) {
  const cause = emotion.lastCause && Date.parse(emotion.lastCauseAt ?? '') >= now.getTime() - 6 * 3_600_000
    ? (CAUSE_LABEL[emotion.lastCause] ?? emotion.lastCause) : '';
  // 近一天的情绪路径：去掉连着重复的，只留最后 5 步——之前把 19 步全列出来，此刻块一半是箭头
  const path = (emotion.trend?.labels || []).filter((l, i, a) => i === 0 || l !== a[i - 1]);
  const trend = path.length >= 2 ? `；近一天走过 ${path.length > 5 ? '…' : ''}${path.slice(-5).join('→')}` : '';
  lines.push(`情绪：${emotionNuance(state, now)}${cause ? `；刚才${cause}` : ''}${trend}`);
  }
  const grudge = grudgeLine(state, now);
  if (grudge) lines.push(grudge);

  const longing = computeLonging(state, now, { timeZone });
  const longingLine = renderLonging(Number(longing ?? 0));
  if (longingLine) lines.push(longingLine);
  else {
    const anticipationLine = renderAnticipation(Number(computeAnticipation(state, now, { timeZone }) ?? 0));
    if (anticipationLine) lines.push(anticipationLine);
  }

  const obsessions = (state.thoughtPool?.obsessions ?? []).filter((o) => Number(o.intensity) >= 0.5).slice(0, 2);
  if (obsessions.length) lines.push(`念头：${obsessions.map((o) => `有个关于「${DRIVE_SHORT[o.key] ?? o.key}」的念头一直在绕`).join('；')}`);

  const extras = [];
  const open = (state.awareness?.candidates ?? []).filter((c) => c.status === 'open').length;
  if (open && isReviewDay(now, { weekday: awarenessReviewWeekday, timeZone })) { counts.awareness = open; extras.push(`${open} 条觉察等你认`); }   // 只在周日提
  const dream = breathDreamContext(state, now, 18, 1);
  if (dream.available) { counts.dream = 1; extras.push('昨夜有梦'); }
  if (boxCount > 0) { counts.box = boxCount; extras.push(`匣子里 ${boxCount} 条${boxSurfaced > 0 ? `（${boxSurfaced} 条要提醒你）` : ''}`); }
  if (extras.length) lines.push(`另外：${extras.join('、')}。细的在 xinchao_context`);

  const text = lines.join('\n');
  // 兜底：块超长或混进数字/key 就整块不给——宁可他这轮没有此刻，也不灌一段错的。
  if (lines.length > NOW_MAX_LINES || text.length > NOW_MAX_CHARS || /\d\.\d|possess|monitor|crave|libido/.test(text.replace(/\d+ (条|句)/g, ''))) {
    return { ok: false, reason: 'render_guard', text: '', lines: lines.length, counts, digest: '', revision: Number(state.revision ?? 0), generatedAt: now.toISOString() };
  }
  return { ok: true, text, lines: lines.length, counts, digest: createHash('sha256').update(text).digest('hex').slice(0, 16), revision: Number(state.revision ?? 0), generatedAt: now.toISOString() };
}
