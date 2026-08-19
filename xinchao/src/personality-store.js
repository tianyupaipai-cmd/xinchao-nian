import { chmod, mkdir, readFile, rename, stat, writeFile } from 'node:fs/promises';
import { dirname } from 'node:path';
import { randomUUID } from 'node:crypto';

const NEUTRAL_SCORE = 70;
const MAX_BIAS = 0.10;

export const PERSONALITY_DIMENSIONS = Object.freeze([
  ['joy', '快乐'],
  ['sorrow', '悲伤'],
  ['anger', '愤怒'],
  ['fear', '恐惧'],
  ['disgust', '厌恶'],
  ['surprise', '惊讶'],
  ['love', '爱与依恋'],
  ['shame', '羞耻与自我评价'],
  ['trust', '信任与社会连接'],
  ['desire', '欲望与动机'],
  ['calm', '平静与安全'],
  ['cognition', '认知与探索'],
  ['conflict', '矛盾与冲突'],
  ['expression', '表达'],
].map(([key, label]) => Object.freeze({ key, label })));

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
    month: String(input.month ?? '').trim().slice(0, 7) || null,
    scoredBy: String(input.scoredBy ?? '').trim() || null,
    updatedAt: String(input.updatedAt ?? '').trim() || null,
    dimensions,
    history,
  };
}

function validateAssessment(input = {}) {
  const month = String(input.month ?? '').trim();
  if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(month)) throw new Error('month 必须是 YYYY-MM');
  if (!Array.isArray(input.dimensions) || input.dimensions.length !== PERSONALITY_DIMENSIONS.length) {
    throw new Error(`dimensions 必须完整包含 ${PERSONALITY_DIMENSIONS.length} 维`);
  }
  const values = new Map();
  for (const raw of input.dimensions) {
    const key = String(raw?.key ?? '').trim();
    if (!key || values.has(key)) throw new Error('dimensions 含缺失或重复 key');
    values.set(key, raw);
  }
  return {
    month,
    dimensions: PERSONALITY_DIMENSIONS.map(({ key, label }) => {
      const raw = values.get(key);
      if (!raw) throw new Error(`dimensions 缺少 ${key}（${label}）`);
      const score = Number(raw.score);
      if (!Number.isFinite(score) || score < 0 || score > 100) throw new Error(`${key}.score 必须在 0–100`);
      const reason = String(raw.reason ?? '').replace(/\s+/g, ' ').trim().slice(0, 1200);
      if (!reason) throw new Error(`${key}.reason 是必填项`);
      return { key, label, score: Number(score.toFixed(2)), reason };
    }),
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
    this.writeQueue = Promise.resolve();
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

  async recordAiAssessment(input, now = new Date()) {
    const operation = this.writeQueue.then(() => this.recordAiAssessmentUnlocked(input, now));
    this.writeQueue = operation.catch(() => {});
    return operation;
  }

  async recordAiAssessmentUnlocked(input, now = new Date()) {
    if (!this.path) throw new Error('PERSONALITY_PATH 未配置');
    const assessment = validateAssessment(input);
    const current = await this.getPersonalityCore(now);
    const previousMonth = current.month
      ?? (/^\d{4}-\d{2}/.test(String(current.updatedAt ?? '')) ? String(current.updatedAt).slice(0, 7) : null);
    const existing = (current.history ?? []).find((item) => item.month === assessment.month)
      ?? (current.scoredBy === 'ai' && previousMonth === assessment.month ? current : null);
    if (existing) {
      return { duplicate: true, month: assessment.month, core: current };
    }

    const previousScores = new Map((current.dimensions ?? []).map((item) => [item.key, Number(item.score)]));
    const dimensions = assessment.dimensions.map((item) => ({
      ...item,
      delta: Number((item.score - (previousScores.get(item.key) ?? NEUTRAL_SCORE)).toFixed(2)),
    }));
    const recordedAt = new Date(now).toISOString();
    const previousSnapshot = current.available && previousMonth && previousMonth !== assessment.month
      ? [{ month: previousMonth, recordedAt: current.updatedAt, dimensions: current.dimensions }]
      : [];
    const history = [...(current.history ?? []), ...previousSnapshot]
      .filter((item, index, values) => values.findIndex((candidate) => candidate.month === item.month) === index)
      .sort((a, b) => String(a.month).localeCompare(String(b.month)));
    const payload = {
      schemaVersion: 1,
      source: 'ai-self-assessment',
      scoredBy: 'ai',
      month: assessment.month,
      updatedAt: recordedAt,
      dimensions,
      history,
    };

    await mkdir(dirname(this.path), { recursive: true });
    const temporary = `${this.path}.${process.pid}.${randomUUID()}.tmp`;
    await writeFile(temporary, `${JSON.stringify(payload, null, 2)}\n`, { encoding: 'utf8', mode: 0o600 });
    await chmod(temporary, 0o600);
    await rename(temporary, this.path);
    this.cache = normalizePersonalityCore(payload, 'ai-self-assessment');
    this.cachedMtimeMs = (await stat(this.path)).mtimeMs;
    this.cachedMonth = monthKey(now);
    return { duplicate: false, month: assessment.month, core: structuredClone(this.cache) };
  }
}
