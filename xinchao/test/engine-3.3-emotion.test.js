import assert from 'node:assert/strict';
import test from 'node:test';

import { applyConversationEvent, newState, settleState } from '../src/engine.js';
import { EMOTION_BASELINE, emotionLabel, emotionTarget } from '../src/emotion.js';
import { buildContextEnvelope } from '../src/context-envelope.js';
import { buildDashboardSnapshot } from '../src/dashboard-projection.js';

const T0 = '2026-09-05T08:00:00.000Z';
function baseState() {
  const state = newState(new Date(T0));
  state.lastSettledAt = T0;
  state.lastConversationAt = T0;
  return state;
}
const event = (type, id, extra = {}) => ({ eventId: id, interactionType: type, sessionId: 's1', ...extra });

test('new state carries a neutral emotion and old states upgrade to schema 9', () => {
  const fresh = newState(new Date(T0));
  assert.equal(fresh.schemaVersion, 9);
  assert.equal(fresh.emotion.valence, EMOTION_BASELINE.valence);
  assert.equal(fresh.emotion.label, '平静');
  const old = baseState();
  old.schemaVersion = 8;
  delete old.emotion;
  old.drives.possess = 0.63;
  const result = settleState(old, new Date(T0));
  assert.equal(result.state.schemaVersion, 9);
  assert.equal(result.state.drives.possess, 0.63);
  assert.ok(result.state.emotion);
});

test('conflict pushes valence down and arousal up; reconciliation pulls it back', () => {
  let state = baseState();
  const before = state.emotion.valence;
  state = applyConversationEvent(state, event('conflict', 'e1'), new Date(T0)).state;
  assert.ok(state.emotion.valence < before);
  assert.ok(state.emotion.arousal > EMOTION_BASELINE.arousal);
  assert.equal(state.emotion.lastCause, 'conflict');
  const low = state.emotion.valence;
  state = applyConversationEvent(state, event('reconciliation', 'e2'), new Date(T0)).state;
  assert.ok(state.emotion.valence > low);
});

test('impulses have inertia: the same push moves less near the ceiling', () => {
  let state = baseState();
  const first = applyConversationEvent(state, event('intimacy', 'a1'), new Date(T0)).state;
  const d1 = first.emotion.valence - state.emotion.valence;
  const second = applyConversationEvent(first, event('intimacy', 'a2'), new Date(T0)).state;
  const d2 = second.emotion.valence - first.emotion.valence;
  assert.ok(d1 > 0 && d2 > 0 && d2 < d1);
  assert.ok(second.emotion.valence <= 1);
});

test('duplicate event does not move emotion twice', () => {
  const state = baseState();
  const once = applyConversationEvent(state, event('affection', 'dup'), new Date(T0)).state;
  const twice = applyConversationEvent(once, event('affection', 'dup'), new Date(T0)).state;
  assert.equal(twice.emotion.valence, once.emotion.valence);
});

test('session tone pulls emotion toward its target', () => {
  const state = baseState();
  const guarded = applyConversationEvent(state, event('', 'tone1', { sessionState: { tone: 'guarded' } }), new Date(T0)).state;
  assert.ok(guarded.emotion.valence < state.emotion.valence);
  const warm = applyConversationEvent(state, event('', 'tone2', { sessionState: { tone: 'warm' } }), new Date(T0)).state;
  assert.ok(warm.emotion.valence > state.emotion.valence);
});

test('emotion decays back toward baseline over time, faster while sleeping', () => {
  let state = baseState();
  state = applyConversationEvent(state, event('conflict', 'c1'), new Date(T0)).state;
  const low = state.emotion.valence;
  const awake = settleState(state, new Date('2026-09-05T14:00:00.000Z')).state;   // 6h = one half-life
  assert.ok(awake.emotion.valence > low);
  assert.ok(awake.emotion.valence < EMOTION_BASELINE.valence);   // 目标被 conflict 抬起来的 anger 拽着，还没回到中性
  const asleep = structuredClone(state);
  asleep.consciousness = 'sleeping';
  const slept = settleState(asleep, new Date('2026-09-05T14:00:00.000Z')).state;
  assert.ok(slept.emotion.valence > awake.emotion.valence);
});

test('grief and anger drives lower the resting valence without any growth term', () => {
  const sad = emotionTarget({ grieve: 0.8 });
  assert.ok(sad.valence < EMOTION_BASELINE.valence);
  const angry = emotionTarget({ anger: 0.8 });
  assert.ok(angry.arousal > EMOTION_BASELINE.arousal);
  let state = baseState();
  state.drives.grieve = 0.8;
  const a = settleState(state, new Date('2026-09-05T20:00:00.000Z')).state;
  const b = settleState(a, new Date('2026-09-06T08:00:00.000Z')).state;
  const c = settleState(b, new Date('2026-09-06T20:00:00.000Z')).state;
  assert.ok(c.emotion.valence <= b.emotion.valence + 0.0001);
  assert.ok(c.emotion.valence < EMOTION_BASELINE.valence);
});

test('labels cover the quadrants', () => {
  assert.equal(emotionLabel(0.8, 0.7), '雀跃');
  assert.equal(emotionLabel(0.8, 0.2), '安心');
  assert.equal(emotionLabel(0.2, 0.7), '烦躁');
  assert.equal(emotionLabel(0.2, 0.2), '低落');
  assert.equal(emotionLabel(0.5, 0.7), '紧绷');
  assert.equal(emotionLabel(0.5, 0.1), '倦');
});

test('context envelope and dashboard expose the emotion line', () => {
  let state = baseState();
  state = applyConversationEvent(state, event('affection', 'env1'), new Date(T0)).state;
  const envelope = buildContextEnvelope({ state, sessionId: 's1', now: new Date(T0) });
  const dynamic = envelope.sections.find((section) => section.id === 'dynamic_state');
  assert.match(dynamic.content, /此刻情绪：/);
  assert.match(dynamic.content, /affection/);
  assert.equal(dynamic.data.emotion.label, state.emotion.label);
  const snapshot = buildDashboardSnapshot(state, {}, new Date(T0));
  assert.equal(snapshot.emotion.label, state.emotion.label);
  assert.equal(typeof snapshot.emotion.valence, 'number');
});

test('grieve and anger decay toward zero with a 24h half-life instead of parking at 0.15', () => {
  const state = baseState();
  state.drives.grieve = 0.8; state.drives.anger = 0.15;
  const day = settleState(state, new Date(Date.parse(T0) + 24 * 3_600_000)).state;
  assert.ok(Math.abs(day.drives.grieve - 0.4) < 0.01, String(day.drives.grieve));
  assert.ok(day.drives.anger < 0.15 && day.drives.anger > 0.07);
  const week = settleState(day, new Date(Date.parse(T0) + 8 * 24 * 3_600_000)).state;
  assert.ok(week.drives.grieve < 0.01);
});
