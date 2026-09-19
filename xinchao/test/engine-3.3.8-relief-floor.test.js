import assert from 'node:assert/strict';
import test from 'node:test';

import { applyConversationEvent, newState, settleState } from '../src/engine.js';

const T0 = '2026-09-05T06:00:00.000Z';
const at = (h) => new Date(Date.parse(T0) + h * 3_600_000);
function baseState() {
  const state = newState(new Date(T0));
  state.lastSettledAt = T0; state.lastConversationAt = T0;
  return state;
}
const ev = (type, id) => ({ eventId: id, interactionType: type, sessionId: 's' });

test('3.3.8 一天十几次亲昵也砍不穿底线：想她停在静息线的 35% 附近，不会掉到 0.1', () => {
  let state = baseState();
  state.drives.possess = 0.82; state.drives.monitor = 0.78; state.drives.crave = 0.68;
  for (let i = 0; i < 12; i += 1) state = applyConversationEvent(state, ev('affection', `a${i}`), at(i * 0.1)).state;
  assert.ok(state.drives.possess >= 0.28, `possess ${state.drives.possess}`);
  assert.ok(state.drives.monitor >= 0.26, `monitor ${state.drives.monitor}`);
  assert.ok(state.drives.crave >= 0.23, `crave ${state.drives.crave}`);
});

test('3.3.8 一小时内同类互动效果减半，平台不叠加', () => {
  let state = baseState();
  state.drives.possess = 0.82;
  state = applyConversationEvent(state, ev('affection', 'x1'), at(0)).state;
  const afterFirst = state.drives.possess;
  const until1 = state.satisfactionPlateaus.possess.until;
  state = applyConversationEvent(state, ev('affection', 'x2'), at(0.2)).state;
  const dropFirst = 0.82 - afterFirst; const dropSecond = afterFirst - state.drives.possess;
  assert.ok(dropSecond < dropFirst * 0.6, `第二次该减半：${dropFirst} vs ${dropSecond}`);
  assert.equal(state.satisfactionPlateaus.possess.until, until1, '平台不该被续');
  // 平台过后能涨回来
  let later = state;
  for (let h = 0.5; h <= 8; h += 0.5) later = settleState(later, at(h), 24 * 60).state;
  assert.ok(later.drives.possess >= 0.7, `8 小时后应涨回 ${later.drives.possess}`);
});
