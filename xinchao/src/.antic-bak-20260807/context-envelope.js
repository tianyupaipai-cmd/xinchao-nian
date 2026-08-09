import { createHash } from 'node:crypto';
import { breathDreamContext, topDrives } from './engine.js';
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

function dynamicSection(state, sessionId, now) {
  return {
    consciousness: state.consciousness,
    fatigue: Number(Number(state.fatigue ?? 0).toFixed(3)),
    topDrives: topDrives(state, 4).map((drive) => ({
      key: drive.key,
      label: drive.label,
      value: Number(Number(drive.value).toFixed(3)),
    })),
    thoughts: thoughtSignals(state),
    session: sessionOverlay(state, sessionId, now),
  };
}

function renderDynamic(value) {
  const drives = value.topDrives
    .map((item) => `${item.label}=${item.value.toFixed(3)}`)
    .join('；');
  const parts = [
    `意识=${value.consciousness}`,
    `疲劳=${value.fatigue.toFixed(3)}`,
    drives ? `当前驱力：${drives}` : '',
  ].filter(Boolean);
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

  const dynamic = dynamicSection(state, safeSessionId, generatedAt);
  const sections = [
    {
      id: 'dynamic_state',
      source: 'xinchao',
      ttl: 'short',
      content: renderDynamic(dynamic),
      data: dynamic,
    },
  ];
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
