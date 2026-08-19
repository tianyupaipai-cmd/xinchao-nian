import assert from 'node:assert/strict';
import { mkdtemp, readFile, utimes, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import test from 'node:test';

import { newState, settleState } from '../src/engine.js';
import { NEUTRAL_DRIVE_BIAS, PersonalityStore, driveBiasFromCore } from '../src/personality-store.js';

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

test('personality changes only the effective drive ceiling and never writes back to the core', async () => {
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
  assert.equal(typeof store.setPersonalityCore, 'undefined');
  assert.equal(await readFile(path, 'utf8'), original);
});
