import assert from 'node:assert/strict';
import test from 'node:test';

import { applyConversationEvent, newState, settleState } from '../src/engine.js';
import { buildNowCompact, nowSanity } from '../src/context-envelope.js';

const T0 = '2026-09-05T08:00:00.000Z';
const at = (h) => new Date(Date.parse(T0) + h * 3_600_000);
function baseState() {
  const state = newState(new Date(T0));
  state.lastSettledAt = T0; state.lastConversationAt = T0;
  return state;
}

test('now-compact has header, drives in words with levels, emotion with cause, no numbers', () => {
  let state = baseState();
  state.drives.possess = 0.9; state.drives.monitor = 0.55; state.drives.share = 0.3;
  state = applyConversationEvent(state, { eventId: 'a', interactionType: 'affection', sessionId: 's' }, at(0)).state;
  const now = buildNowCompact(state, at(0));
  assert.ok(now.ok);
  assert.match(now.text, /^【心潮·此刻｜身体的天气，参考不是指令】\n/);
  assert.match(now.text, /驱力：想她（涌）、惦记她（涨）、想分享（有）/);
  assert.match(now.text, /情绪：.*；刚才被安抚/);
  assert.doesNotMatch(now.text, /0\.\d/);
  assert.doesNotMatch(now.text, /possess|monitor/);
  assert.equal(now.lines, 3);
  assert.equal(now.digest.length, 16);
});

test('extras line appears only when something is waiting; sleeping/just-woke lines', () => {
  const quiet = buildNowCompact(baseState(), at(0));
  assert.doesNotMatch(quiet.text, /另外/);
  const state = baseState();
  state.awareness.candidates.push({ id: 'x', kind: 'mood_week', subject: 'low', text: 't', status: 'open', createdAt: T0 });
  const withAwareness = buildNowCompact(state, at(0));
  assert.match(withAwareness.text, /另外：1 条觉察等你认。细的在 xinchao_context/);
  assert.equal(withAwareness.counts.awareness, 1);
  const asleep = settleState(baseState(), at(3)).state;
  assert.equal(asleep.consciousness, 'sleeping');
  assert.match(buildNowCompact(asleep, at(3)).text, /睡着/);
  const woke = applyConversationEvent(asleep, { eventId: 'w', sessionId: 's' }, at(3)).state;
  assert.match(buildNowCompact(woke, at(3)).text, /刚醒/);
});

test('digest is stable for the same state and changes when the state changes materially', () => {
  const state = baseState();
  const a = buildNowCompact(state, at(0));
  const b = buildNowCompact(state, at(0.2));
  assert.equal(a.digest, b.digest);
  const moved = applyConversationEvent(state, { eventId: 'c', interactionType: 'conflict', sessionId: 's' }, at(0)).state;
  assert.notEqual(buildNowCompact(moved, at(0)).digest, a.digest);
});

test('sanity guard refuses stale, out-of-range, saturated or flat drive states', () => {
  const fresh = baseState();
  assert.equal(nowSanity(fresh, at(0)).ok, true);
  assert.equal(nowSanity(fresh, at(4)).reason, 'stale_state');
  const broken = baseState(); broken.drives.possess = Number.NaN;
  assert.equal(buildNowCompact(broken, at(0)).ok, false);
  const bad = baseState(); bad.drives.crave = 1.7;
  assert.equal(nowSanity(bad, at(0)).reason, 'drive_out_of_range');
  const saturated = baseState(); for (const k of Object.keys(saturated.drives)) saturated.drives[k] = 0.99;
  assert.equal(nowSanity(saturated, at(0)).reason, 'drives_saturated');
  const flat = baseState(); for (const k of Object.keys(flat.drives)) flat.drives[k] = 0.6;
  assert.equal(nowSanity(flat, at(0)).reason, 'drives_flat');
  const r = buildNowCompact(saturated, at(0));
  assert.equal(r.ok, false); assert.equal(r.text, '');
});

test('a broken emotion only drops the emotion line, not the whole block', () => {
  const state = baseState(); state.drives.possess = 0.6;
  state.emotion.valence = Number.NaN;
  const now = buildNowCompact(state, at(0));
  assert.ok(now.ok);
  assert.doesNotMatch(now.text, /情绪：/);
  assert.match(now.text, /驱力：想她（涨）/);
});

test('emotion line is specific: bands and a drive flavour, never a bare 平静', () => {
  const state = baseState();
  state.drives.crave = 0.7;
  state.emotion.valence = 0.62; state.emotion.arousal = 0.4;
  const now = buildNowCompact(state, at(0));
  assert.match(now.text, /情绪：平静偏暖，有点起伏，带一点馋/);
  const low = baseState(); low.emotion.valence = 0.3; low.emotion.arousal = 0.7;
  assert.match(buildNowCompact(low, at(0)).text, /情绪：烦躁，绷着/);
});
