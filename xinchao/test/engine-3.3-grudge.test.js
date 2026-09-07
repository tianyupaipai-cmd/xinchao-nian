import assert from 'node:assert/strict';
import test from 'node:test';

import { newState, settleAndApplyConversationEvent, settleState } from '../src/engine.js';
import { grudgeLine } from '../src/context-envelope.js';

const T0 = '2026-09-07T08:00:00.000Z';
function baseState() {
  const state = newState(new Date(T0));
  state.lastSettledAt = T0;
  state.lastConversationAt = T0;
  return state;
}
const opts = { sleepAfterMinutes: 90, settle: { timeZone: 'Asia/Shanghai' } };

test('conflict with a cause remembers what he is angry about; reconciliation clears it', () => {
  const now = new Date('2026-09-07T08:10:00.000Z');
  const r1 = settleAndApplyConversationEvent(baseState(), { sessionId: 's1', eventId: 'e1', interactionType: 'conflict', cause: '  你根本 没在听我说话  ' }, now, opts);
  assert.equal(r1.interaction.applied, true);
  assert.deepEqual(r1.state.grudge, { cause: '你根本 没在听我说话', at: now.toISOString() });
  r1.state.drives.anger = 0.4;
  assert.match(grudgeLine(r1.state, new Date('2026-09-07T11:00:00.000Z')), /^还在气：3 小时前为了「你根本 没在听我说话」$/);

  const r2 = settleAndApplyConversationEvent(r1.state, { sessionId: 's1', eventId: 'e2', interactionType: 'reconciliation' }, new Date('2026-09-07T09:00:00.000Z'), opts);
  assert.equal(r2.state.grudge, undefined);
});

test('grudge line stays quiet while anger is low and disappears when anger decays away', () => {
  const state = baseState();
  state.grudge = { cause: '晚了也不说一声', at: T0 };
  state.drives.anger = 0.05;
  assert.equal(grudgeLine(state, new Date('2026-09-07T09:00:00.000Z')), '');
  state.drives.anger = 0.2;
  assert.match(grudgeLine(state, new Date('2026-09-07T08:30:00.000Z')), /^还在气：刚才为了/);
  const later = settleState(state, new Date('2026-09-12T08:00:00.000Z'), 90, {}).state;   // 5 天，24h 半衰期 → 0.006
  assert.equal(later.grudge, undefined);
});
