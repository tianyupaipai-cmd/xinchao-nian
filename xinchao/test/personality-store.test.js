import assert from 'node:assert/strict';
import { mkdtemp, readFile, utimes, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import test from 'node:test';

import { newState, settleState } from '../src/engine.js';
import { NEUTRAL_DRIVE_BIAS, PERSONALITY_DIMENSIONS, PersonalityStore, driveBiasFromCore } from '../src/personality-store.js';

test('missing or damaged private personality mirror is neutral and non-fatal', async () => {
  const missing = new PersonalityStore('/definitely/missing/personality.json');
  assert.deepEqual(await missing.getDriveBias(), NEUTRAL_DRIVE_BIAS);

  const directory = await mkdtemp(join(tmpdir(), 'xinchao-personality-'));
  const path = join(directory, 'personality.json');
  await writeFile(path, '{broken', 'utf8');
  const damaged = new PersonalityStore(path);
  assert.deepEqual(await damaged.getDriveBias(), NEUTRAL_DRIVE_BIAS);
});

test('only the four approved personality groups bias drives and remain capped at ten percent', () => {
  const bias = driveBiasFromCore({ dimensions: [
    { label: '爱与依恋', score: 100 },
    { label: '表达', score: 40 },
    { label: '平静与安全', score: 40 },
    { label: '欲望与动机', score: 100 },
    { label: '恐惧', score: 0 },
  ] });
  assert.equal(bias.possess, 1.1);
  assert.equal(bias.crave, 1.1);
  assert.equal(bias.share, 0.9);
  assert.equal(bias.grieve, 1.1);
  assert.equal(bias.monitor, 1.1);
  assert.equal(bias.libido, 1.1);
  assert.equal(bias.curiosity, 1.1);
  assert.equal(Object.hasOwn(bias, 'anger'), false);
});

test('the cached monthly mirror reloads when the private file changes', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'xinchao-personality-reload-'));
  const path = join(directory, 'personality.json');
  await writeFile(path, JSON.stringify({
    dimensions: [{ key: 'attachment', label: '爱与依恋', score: 70 }],
  }), 'utf8');
  const store = new PersonalityStore(path);
  assert.equal((await store.getDriveBias()).possess, 1);

  await writeFile(path, JSON.stringify({
    dimensions: [{ key: 'attachment', label: '爱与依恋', score: 100 }],
  }), 'utf8');
  const changedAt = new Date(Date.now() + 2_000);
  await utimes(path, changedAt, changedAt);
  assert.equal((await store.getDriveBias()).possess, 1.1);
});

test('personality changes only the effective drive ceiling and the drive engine never writes back to the core', async () => {
  const state = newState(new Date('2026-08-19T08:00:00.000Z'));
  state.lastSettledAt = '2026-08-19T08:00:00.000Z';
  state.drives.possess = 0.84;
  const neutral = settleState(state, new Date('2026-08-19T09:00:00.000Z'), 9999, {
    driveBias: { possess: 1 },
  }).state;
  const lifted = settleState(state, new Date('2026-08-19T09:00:00.000Z'), 9999, {
    driveBias: { possess: 1.1 },
  }).state;
  assert.ok(lifted.drives.possess > neutral.drives.possess);

  const directory = await mkdtemp(join(tmpdir(), 'xinchao-personality-readonly-'));
  const path = join(directory, 'personality.json');
  const original = JSON.stringify({ dimensions: [{ label: '爱与依恋', score: 83 }] });
  await writeFile(path, original, 'utf8');
  const store = new PersonalityStore(path);
  await store.getDriveBias();
  assert.equal(await readFile(path, 'utf8'), original);
});

test('AI monthly assessment writes all 14 dimensions privately and retry is idempotent', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'xinchao-personality-ai-'));
  const path = join(directory, 'personality.json');
  const store = new PersonalityStore(path);
  const dimensions = PERSONALITY_DIMENSIONS.map(({ key }, index) => ({
    key,
    score: 60 + index,
    reason: `AI 对 ${key} 的月度回顾`,
  }));
  const first = await store.recordAiAssessment({ month: '2026-08', dimensions }, new Date('2026-08-31T12:00:00Z'));
  assert.equal(first.duplicate, false);
  assert.equal(first.core.scoredBy, 'ai');
  assert.equal(first.core.dimensions.length, 14);
  assert.equal(first.core.dimensions[0].delta, -10);

  const saved = JSON.parse(await readFile(path, 'utf8'));
  assert.equal(saved.source, 'ai-self-assessment');
  assert.equal(saved.month, '2026-08');
  assert.equal(saved.dimensions[6].label, '爱与依恋');

  const duplicate = await store.recordAiAssessment({ month: '2026-08', dimensions }, new Date('2026-08-31T12:01:00Z'));
  assert.equal(duplicate.duplicate, true);
});

test('simultaneous AI retries cannot create two assessments for one month', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'xinchao-personality-concurrent-'));
  const store = new PersonalityStore(join(directory, 'personality.json'));
  const dimensions = PERSONALITY_DIMENSIONS.map(({ key }) => ({ key, score: 70, reason: 'AI 月度回顾' }));
  const results = await Promise.all([
    store.recordAiAssessment({ month: '2026-08', dimensions }, new Date('2026-08-31T12:00:00Z')),
    store.recordAiAssessment({ month: '2026-08', dimensions }, new Date('2026-08-31T12:00:01Z')),
  ]);
  assert.deepEqual(results.map((result) => result.duplicate).sort(), [false, true]);
});

test('AI assessment rejects incomplete or unknown personality dimensions', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'xinchao-personality-invalid-'));
  const store = new PersonalityStore(join(directory, 'personality.json'));
  await assert.rejects(
    store.recordAiAssessment({ month: '2026-08', dimensions: [] }),
    /完整包含 14 维/,
  );
  const invalid = PERSONALITY_DIMENSIONS.map(({ key }) => ({ key, score: 70, reason: '月度回顾' }));
  invalid[0] = { key: 'unknown', score: 70, reason: '月度回顾' };
  await assert.rejects(
    store.recordAiAssessment({ month: '2026-08', dimensions: invalid }),
    /缺少 joy/,
  );
});
