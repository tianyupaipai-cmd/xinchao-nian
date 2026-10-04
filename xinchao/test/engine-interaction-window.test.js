import assert from 'node:assert/strict';
import test from 'node:test';

import { newState, settleAndApplyConversationEvent } from '../src/engine.js';

const T0 = '2026-09-28T10:00:00.000Z';
const opts = { sleepAfterMinutes: 600, settle: { timeZone: 'Asia/Shanghai' } };
function baseState() {
  const state = newState(new Date(T0));
  state.lastSettledAt = T0;
  state.lastConversationAt = T0;
  return state;
}
const at = (min) => new Date(Date.parse(T0) + min * 60_000);

test('interaction effects are limited per rolling 4-hour window, not per calendar day', () => {
  let state = baseState();
  for (let i = 0; i < 8; i += 1) {
    const r = settleAndApplyConversationEvent(state, { sessionId: 's', eventId: `a${i}`, interactionType: 'companionship' }, at(i * 5), opts);
    assert.equal(r.interaction.applied, true, `#${i} should apply`);
    state = r.state;
  }
  const ninth = settleAndApplyConversationEvent(state, { sessionId: 's', eventId: 'a8', interactionType: 'affection' }, at(45), opts);
  assert.equal(ninth.interaction.applied, false);
  assert.equal(ninth.interaction.reasonCode, 'window_effect_limit');
  // 4 小时后最早那几次滑出窗口，又有名额
  const later = settleAndApplyConversationEvent(ninth.state, { sessionId: 's', eventId: 'a9', interactionType: 'affection' }, at(4 * 60 + 6), opts);
  assert.equal(later.interaction.applied, true);
});

test('conflict / loss / reconciliation never use up the window and always apply', () => {
  let state = baseState();
  for (let i = 0; i < 8; i += 1) state = settleAndApplyConversationEvent(state, { sessionId: 's', eventId: `a${i}`, interactionType: 'companionship' }, at(i), opts).state;
  const before = state.drives.anger;
  const c = settleAndApplyConversationEvent(state, { sessionId: 's', eventId: 'c1', interactionType: 'conflict', cause: '你又不听我说话' }, at(10), opts);
  assert.equal(c.interaction.applied, true);
  assert.ok(c.state.drives.anger - before >= 0.24, 'one conflict should lift anger past the quiet line');
  assert.equal(c.state.interactionRecent.length, 8, 'conflict does not take a slot');
  const l = settleAndApplyConversationEvent(c.state, { sessionId: 's', eventId: 'l1', interactionType: 'loss' }, at(11), opts);
  assert.equal(l.interaction.applied, true);
  const r = settleAndApplyConversationEvent(l.state, { sessionId: 's', eventId: 'r1', interactionType: 'reconciliation' }, at(12), opts);
  assert.equal(r.interaction.applied, true);
  assert.ok(r.state.drives.anger < l.state.drives.anger);
});
