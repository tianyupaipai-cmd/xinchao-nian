import { readFile, stat } from 'node:fs/promises';

const NEUTRAL_SCORE = 70;
const MAX_BIAS = 0.10;

const CORE_TO_DRIVES = Object.freeze({
  '爱与依恋': { drives: ['possess', 'crave'], direction: 1 },
  '表达': { drives: ['share'], direction: 1 },
  '平静与安全': { drives: ['grieve', 'monitor'], direction: -1 },
  '欲望与动机': { drives: ['libido', 'curiosity'], direction: 1 },
});

export const NEUTRAL_DRIVE_BIAS = Object.freeze({
  possess: 1,
  crave: 1,
  share: 1,
  grieve: 1,
  monitor: 1,
  libido: 1,
  curiosity: 1,
});

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, Number(value)));
}

function monthKey(date = new Date()) {
  const value = new Date(date);
  return `${value.getUTCFullYear()}-${String(value.getUTCMonth() + 1).padStart(2, '0')}`;
}

function normalizeDimension(value, fallbackKey = '') {
  const item = value && typeof value === 'object' ? value : {};
  const key = String(item.key ?? fallbackKey).trim();
  const label = String(item.label ?? key).trim();
  const score = clamp(Number(item.score ?? NEUTRAL_SCORE), 0, 100);
  const delta = Number(item.delta);
  return {
    key,
    label,
    score: Number.isFinite(score) ? score : NEUTRAL_SCORE,
    delta: Number.isFinite(delta) ? delta : 0,
    reason: String(item.reason ?? '').trim().slice(0, 1200),
  };
}

function normalizeDimensions(input) {
  if (Array.isArray(input)) return input.map((item) => normalizeDimension(item)).filter((item) => item.key);
  if (input && typeof input === 'object') {
    return Object.entries(input)
      .map(([key, value]) => normalizeDimension(value, key))
      .filter((item) => item.key);
  }
  return [];
}

function normalizeSnapshot(input = {}) {
  return {
    month: String(input.month ?? '').trim().slice(0, 7) || null,
    recordedAt: String(input.recordedAt ?? input.updatedAt ?? '').trim() || null,
    dimensions: normalizeDimensions(input.dimensions ?? input.core ?? input.scores),
  };
}

export function normalizePersonalityCore(input = {}, source = 'private-state') {
  const dimensions = normalizeDimensions(input.dimensions ?? input.core ?? input.scores ?? input);
  const history = Array.isArray(input.history ?? input.snapshots)
    ? (input.history ?? input.snapshots).map(normalizeSnapshot).filter((item) => item.dimensions.length)
    : [];
  return {
    schemaVersion: 1,
    available: dimensions.length > 0,
    source,
    updatedAt: String(input.updatedAt ?? '').trim() || null,
    dimensions,
    history,
  };
}

export function driveBiasFromCore(core = {}) {
  const bias = { ...NEUTRAL_DRIVE_BIAS };
  const dimensions = Array.isArray(core.dimensions) ? core.dimensions : [];
  for (const [label, mapping] of Object.entries(CORE_TO_DRIVES)) {
    const dimension = dimensions.find((item) => item?.label === label || item?.key === label);
    if (!dimension) continue;
    // 70 为中性；偏离 30 分对应 10%，超出仍硬封顶在 ±10%。
    const signed = clamp((Number(dimension.score) - NEUTRAL_SCORE) / 30, -1, 1);
    const factor = 1 + mapping.direction * signed * MAX_BIAS;
    for (const drive of mapping.drives) bias[drive] = Number(clamp(factor, 0.9, 1.1).toFixed(4));
  }
  return bias;
}

export class PersonalityStore {
  constructor(path) {
    this.path = String(path ?? '').trim();
    this.cache = null;
    this.cachedMtimeMs = null;
    this.cachedMonth = null;
  }

  async getPersonalityCore(now = new Date()) {
    if (!this.path) return normalizePersonalityCore({}, 'not-configured');
    try {
      const file = await stat(this.path);
      const currentMonth = monthKey(now);
      if (this.cache && this.cachedMtimeMs === file.mtimeMs && this.cachedMonth === currentMonth) {
        return structuredClone(this.cache);
      }
      const parsed = JSON.parse(await readFile(this.path, 'utf8'));
      this.cache = normalizePersonalityCore(parsed);
      this.cachedMtimeMs = file.mtimeMs;
      this.cachedMonth = currentMonth;
      return structuredClone(this.cache);
    } catch (error) {
      // 私有镜像缺失或损坏时必须 fail-safe：不影响心潮运行，偏置全为 1.0。
      return normalizePersonalityCore({}, error?.code === 'ENOENT' ? 'missing' : 'invalid');
    }
  }

  async getDriveBias(now = new Date()) {
    return driveBiasFromCore(await this.getPersonalityCore(now));
  }
}
