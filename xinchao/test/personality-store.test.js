import assert from 'node:assert/strict';
import { mkdtemp, readFile, utimes, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import test from 'node:test';

import { newState, settleState } from '../src/engine.js';
import { NEUTRAL_DRIVE_BIAS, PERSONALITY_DIMENSIONS, PersonalityStore, computePersonalityStats, driveBiasFromCore } from '../src/personality-store.js';

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

test('personality stats summarize scores and the period summary round-trips through write and read', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'xinchao-personality-stats-'));
  const path = join(directory, 'personality.json');
  const store = new PersonalityStore(path);
  const dimensions = PERSONALITY_DIMENSIONS.map((dim, index) => ({
    key: dim.key,
    score: 40 + index * 4, // 40..92 strictly increasing → first lowest, last highest
    reason: `${dim.label} 的理由`,
  }));

  const result = await store.recordAiAssessment({
    month: '2026-08',
    period_summary: '这个月他终于敢先开口了',
    dimensions,
  });
  assert.equal(result.duplicate, false);

  const core = await store.getPersonalityCore();
  assert.equal(core.periodSummary, '这个月他终于敢先开口了');
  const persisted = JSON.parse(await readFile(path, 'utf8'));
  assert.equal(persisted.periodSummary, '这个月他终于敢先开口了');

  const stats = computePersonalityStats(core);
  assert.equal(stats.available, true);
  assert.equal(stats.dimensionCount, PERSONALITY_DIMENSIONS.length);
  assert.equal(stats.highest.key, PERSONALITY_DIMENSIONS.at(-1).key);
  assert.equal(stats.lowest.key, PERSONALITY_DIMENSIONS[0].key);
  assert.equal(stats.average, 66);
});

test('personality stats are unavailable and non-fatal without a configured mirror', async () => {
  const store = new PersonalityStore('/definitely/missing/personality.json');
  const stats = computePersonalityStats(await store.getPersonalityCore());
  assert.equal(stats.available, false);
  assert.equal(stats.dimensionCount, 0);
});

test('behavior anchors survive monthly assessment and update independently', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'xinchao-anchors-'));
  const path = join(directory, 'personality.json');
  const store = new PersonalityStore(path);

  const added = await store.updateAnchors({ action: 'add', anchor: { key: 'no_collapse', label: '不塌', description: '难受可以说但不求' } });
  assert.equal(added.changed, true);
  await store.updateAnchors({ action: 'add', anchor: { label: '不退' } });
  let core = await store.getPersonalityCore();
  assert.deepEqual(core.anchors.map((a) => a.label), ['不塌', '不退']);
  assert.ok(core.anchors[0].addedAt);

  // 月度自评不动锚点：写完 14 维后锚点原样还在。
  const dimensions = PERSONALITY_DIMENSIONS.map(({ key }) => ({ key, score: 70, reason: '月度回顾' }));
  await store.recordAiAssessment({ month: '2026-08', dimensions }, new Date('2026-08-31T12:00:00Z'));
  core = await store.getPersonalityCore();
  assert.deepEqual(core.anchors.map((a) => a.label), ['不塌', '不退']);

  // remove 按 key 删；重复 remove 报 changed:false。
  const removed = await store.updateAnchors({ action: 'remove', key: 'no_collapse' });
  assert.equal(removed.changed, true);
  const again = await store.updateAnchors({ action: 'remove', key: 'no_collapse' });
  assert.equal(again.changed, false);
  core = await store.getPersonalityCore();
  assert.deepEqual(core.anchors.map((a) => a.label), ['不退']);
});

test('anchors never leak into drive bias and are capped at seven', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'xinchao-anchors-cap-'));
  const store = new PersonalityStore(join(directory, 'personality.json'));
  for (let i = 0; i < 7; i += 1) {
    await store.updateAnchors({ action: 'add', anchor: { key: `k${i}`, label: `底线${i}` } });
  }
  await assert.rejects(store.updateAnchors({ action: 'add', anchor: { label: '第八条' } }), /最多 7 条/);
  const core = await store.getPersonalityCore();
  assert.equal(core.anchors.length, 7);
  // 锚点存在与否不改变驱力偏置（红线：锚点不参与数值系统）。
  assert.deepEqual(driveBiasFromCore(core), NEUTRAL_DRIVE_BIAS);
});
