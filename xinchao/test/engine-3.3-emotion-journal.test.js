import assert from 'node:assert/strict';
import test from 'node:test';

import { applyConversationEvent, newState, settleState } from '../src/engine.js';
import { emotionTrend, renderEmotionTrend } from '../src/emotion.js';
import { buildContextEnvelope } from '../src/context-envelope.js';
import { buildDashboardSnapshot } from '../src/dashboard-projection.js';

const T0 = '2026-09-05T08:00:00.000Z';
const at = (h) => new Date(Date.parse(T0) + h * 3_600_000);
function baseState() {
  const state = newState(new Date(T0));
  state.lastSettledAt = T0;
  state.lastConversationAt = T0;
  return state;
}
const ev = (type, id) => ({ eventId: id, interactionType: type, sessionId: 's1' });

test('impulses and settles write journal samples with throttling', () => {
  let state = baseState();
  assert.equal(state.emotionJournal.length, 0);
  state = applyConversationEvent(state, ev('conflict', 'c1'), at(0)).state;     // label changes → sample
  assert.equal(state.emotionJournal.length, 1);
  assert.equal(state.emotionJournal[0].cause, 'conflict');
  state = applyConversationEvent(state, ev('conflict', 'c2'), at(0.1)).state;   // same label, <30min → no sample
  const afterSecond = state.emotionJournal.length;
  assert.ok(afterSecond <= 2);
  state = settleState(state, at(1)).state;                                       // <2h since last → maybe no new
  state = settleState(state, at(4)).state;                                       // ≥2h → sample
  assert.ok(state.emotionJournal.length > afterSecond);
  assert.equal(state.emotionJournal.at(-1).cause, null);
});

test('day digest aggregates in Asia/Shanghai days and prunes old days', () => {
  let state = baseState();
  state = applyConversationEvent(state, ev('affection', 'a1'), at(0)).state;    // 16:00 上海 → 09-05
  state = applyConversationEvent(state, ev('conflict', 'a2'), at(9)).state;     // 01:00 上海 → 09-06
  assert.ok(state.emotionDays['2026-09-05']);
  assert.ok(state.emotionDays['2026-09-06']);
  assert.equal(state.emotionDays['2026-09-06'].causes.conflict, 1);
  state.emotionDays['2026-07-01'] = { samples: 1, meanValence: 0.5, meanArousal: 0.3, minValence: 0.5, maxArousal: 0.3, labels: {}, causes: {} };
  state = settleState(state, at(12)).state;
  assert.equal(state.emotionDays['2026-07-01'], undefined);
});

test('trend line appears in envelope once emotion has moved, and dashboard exposes journal', () => {
  let state = baseState();
  state = applyConversationEvent(state, ev('conflict', 't1'), at(0)).state;
  state = applyConversationEvent(state, ev('reconciliation', 't2'), at(1)).state;
  state = applyConversationEvent(state, ev('intimacy', 't3'), at(2)).state;
  const trend = emotionTrend(state, at(2));
  assert.ok(trend.labels.length >= 2);
  assert.match(renderEmotionTrend(trend), /近24小时情绪走过：/);
  const envelope = buildContextEnvelope({ state, sessionId: 's1', now: at(2) });
  assert.match(envelope.sections[0].content, /情绪走过/);
  const snapshot = buildDashboardSnapshot(state, {}, at(2));
  assert.ok(Array.isArray(snapshot.emotion.journal) && snapshot.emotion.journal.length >= 2);
  assert.ok(snapshot.emotion.days['2026-09-05']);
});

test('old states without a journal upgrade cleanly', () => {
  const old = baseState();
  delete old.emotionJournal; delete old.emotionDays;
  const next = settleState(old, at(3)).state;
  assert.ok(Array.isArray(next.emotionJournal));
  assert.equal(typeof next.emotionDays, 'object');
});
