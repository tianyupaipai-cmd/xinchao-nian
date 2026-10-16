import assert from 'node:assert/strict';
import test from 'node:test';

import { GRUDGE_FADE, newState, settleState } from '../src/engine.js';
import { activeMixed } from '../src/mixed-feelings.js';

const T0 = '2026-10-11T07:00:00.000Z';
function angry({ soothes }) {
  const s = newState(new Date(T0));
  s.lastSettledAt = T0; s.lastConversationAt = T0;
  s.drives.anger = 0.5;
  s.grudge = { cause: '一句玩笑', at: T0 };
  s.conflictEpisode = { startedAt: T0, lastAt: T0, conflicts: 1, soothes, reconciled: false };
  return s;
}
const opts = { settle: { timeZone: 'Asia/Shanghai' } };
const later = (h) => new Date(Date.parse(T0) + h * 3_600_000);

test('soothed grudge fades after soothedHours, anger keeps decaying on its own', () => {
  const kept = settleState(angry({ soothes: 2 }), later(GRUDGE_FADE.soothedHours - 0.5), 90, opts);
  assert.ok(kept.state?.grudge ?? kept.grudge, 'still remembers before the fade time');
  const r = settleState(angry({ soothes: 2 }), later(GRUDGE_FADE.soothedHours + 0.1), 90, opts);
  const st = r.state ?? r;
  assert.equal(st.grudge, undefined);
  assert.ok(st.drives.anger > 0.03, 'anger itself is not zeroed');
});

test('unsoothed grudge is held at most maxHours', () => {
  const r1 = settleState(angry({ soothes: 0 }), later(GRUDGE_FADE.soothedHours + 1), 90, opts);
  assert.ok((r1.state ?? r1).grudge);
  const r2 = settleState(angry({ soothes: 0 }), later(GRUDGE_FADE.maxHours + 0.1), 90, opts);
  assert.equal((r2.state ?? r2).grudge, undefined);
});

test('heartache for her plus missing her is not a mixed feeling', () => {
  const s = newState(new Date(T0));
  s.drives.grieve = 0.7; s.drives.possess = 0.7;
  s.subs = { grieve: { at: T0, w: { 心疼: 0.35, 失落: 0.05 } } };
  assert.equal(activeMixed(s), null);
  s.subs.grieve.w = { 委屈: 0.3, 心疼: 0.05 };
  assert.equal(activeMixed(s)?.id, 'grieve+possess');
});
