import { createHash, randomUUID } from 'node:crypto';
import { mkdir, open } from 'node:fs/promises';
import { dirname } from 'node:path';

const SAFE_DETAIL_KEYS = new Set([
  'alreadyDelivered',
  'barkSent',
  'changed',
  'daytimeSent',
  'delivered',
  'dreamCreated',
  'duplicate',
  'estimatedTokens',
  'force',
  'kind',
  'interactionApplied',
  'mode',
  'ombreIncluded',
  'reasonCode',
  'sectionCount',
  'sessionCreated',
  'sessionExpired',
  'status',
  'settledHours',
]);

const PRIVATE_DETAIL_KEYS = new Set([
  'awareness',
  'body',
  'content',
  'dream',
  'material',
  'message',
  'prompt',
  'query',
  'residue',
  'text',
  'title',
]);

function finite(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function compactString(value, maxLength = 80) {
  return String(value ?? '').replace(/\s+/g, ' ').trim().slice(0, maxLength);
}

function count(value) {
  return Array.isArray(value) ? value.length : 0;
}

function safeDetails(value = {}) {
  const safe = {};
  for (const [key, item] of Object.entries(value ?? {})) {
    if (!SAFE_DETAIL_KEYS.has(key) || PRIVATE_DETAIL_KEYS.has(key.toLowerCase())) continue;
    if (typeof item === 'boolean' || typeof item === 'number') safe[key] = item;
    else if (typeof item === 'string') safe[key] = compactString(item);
  }
  return safe;
}

function driveDeltas(before = {}, after = {}) {
  const result = {};
  const keys = new Set([
    ...Object.keys(before?.drives ?? {}),
    ...Object.keys(after?.drives ?? {}),
  ]);
  for (const key of keys) {
    const delta = finite(after?.drives?.[key]) - finite(before?.drives?.[key]);
    if (Math.abs(delta) >= 0.0001) result[key] = Number(delta.toFixed(4));
  }
  return result;
}

export function summarizeTransition(before = {}, after = {}) {
  const summary = {
    consciousness: before.consciousness === after.consciousness
      ? null
      : { from: compactString(before.consciousness), to: compactString(after.consciousness) },
    fatigueDelta: Number((finite(after.fatigue) - finite(before.fatigue)).toFixed(4)),
    driveDeltas: driveDeltas(before, after),
    counts: {
      dreams: count(after.recentDreams) - count(before.recentDreams),
      flashThoughts: count(after.thoughtPool?.flash) - count(before.thoughtPool?.flash),
      obsessions: count(after.thoughtPool?.obsessions) - count(before.thoughtPool?.obsessions),
      sessionOverlays: Object.keys(after.sessionOverlays ?? {}).length
        - Object.keys(before.sessionOverlays ?? {}).length,
    },
  };
  if (!summary.consciousness) delete summary.consciousness;
  if (summary.fatigueDelta === 0) delete summary.fatigueDelta;
  if (!Object.keys(summary.driveDeltas).length) delete summary.driveDeltas;
  for (const [key, value] of Object.entries(summary.counts)) {
    if (!value) delete summary.counts[key];
  }
  if (!Object.keys(summary.counts).length) delete summary.counts;
  return summary;
}

export function digestContext(value) {
  return createHash('sha256').update(String(value ?? ''), 'utf8').digest('hex').slice(0, 16);
}

export class TransitionJournal {
  #queue = Promise.resolve();

  constructor(path) {
    this.path = path;
  }

  recordTransition({
    before = {},
    after = {},
    type,
    source = 'system',
    sessionId = '',
    eventId = '',
    details = {},
    force = false,
    at = new Date(),
  }) {
    const delta = summarizeTransition(before, after);
    const revisionBefore = finite(before.revision);
    const revisionAfter = finite(after.revision);
    if (!force && revisionBefore === revisionAfter && !Object.keys(delta).length) return Promise.resolve(null);
    return this.append({
      id: randomUUID(),
      at: new Date(at).toISOString(),
      type: compactString(type || 'state_transition'),
      source: compactString(source || 'system'),
      sessionId: compactString(sessionId, 120),
      eventId: compactString(eventId, 120),
      revisionBefore,
      revisionAfter,
      delta,
      details: safeDetails(details),
    });
  }

  recordContext({
    mode,
    sessionId,
    digest,
    estimatedTokens,
    sectionCount,
    delivered,
    alreadyDelivered,
    ombreIncluded,
    at = new Date(),
  }) {
    return this.append({
      id: randomUUID(),
      at: new Date(at).toISOString(),
      type: 'context_envelope',
      source: 'context-adapter',
      sessionId: compactString(sessionId, 120),
      revisionBefore: null,
      revisionAfter: null,
      delta: {},
      contextDigest: compactString(digest, 32),
      details: safeDetails({
        mode,
        estimatedTokens,
        sectionCount,
        delivered,
        alreadyDelivered,
        ombreIncluded,
      }),
    });
  }

  append(record) {
    const operation = this.#queue.then(async () => {
      await mkdir(dirname(this.path), { recursive: true });
      const handle = await open(this.path, 'a', 0o600);
      try {
        await handle.chmod(0o600);
        await handle.appendFile(`${JSON.stringify(record)}\n`, 'utf8');
        await handle.sync();
      } finally {
        await handle.close();
      }
      return record;
    });
    this.#queue = operation.catch(() => {});
    return operation;
  }

  async list({ limit = 50, since = '', types = [], maxBytes = 512 * 1024 } = {}) {
    const boundedLimit = Math.max(1, Math.min(200, Number(limit) || 50));
    const boundedBytes = Math.max(16 * 1024, Math.min(2 * 1024 * 1024, Number(maxBytes) || 512 * 1024));
    const sinceTimestamp = Date.parse(since ?? '');
    const allowedTypes = new Set((Array.isArray(types) ? types : [types])
      .map((value) => compactString(value, 80))
      .filter(Boolean));
    let handle;
    try {
      handle = await open(this.path, 'r');
      const info = await handle.stat();
      const size = Math.min(info.size, boundedBytes);
      if (!size) return [];
      const buffer = Buffer.alloc(size);
      await handle.read(buffer, 0, size, info.size - size);
      let text = buffer.toString('utf8');
      if (info.size > size) text = text.slice(text.indexOf('\n') + 1);
      return text.split('\n')
        .filter(Boolean)
        .map((line) => {
          try { return JSON.parse(line); }
          catch { return null; }
        })
        .filter((record) => record && (!allowedTypes.size || allowedTypes.has(record.type)))
        .filter((record) => !Number.isFinite(sinceTimestamp) || Date.parse(record.at ?? '') >= sinceTimestamp)
        .slice(-boundedLimit)
        .reverse();
    } catch (error) {
      if (error.code === 'ENOENT') return [];
      throw error;
    } finally {
      await handle?.close();
    }
  }
}
