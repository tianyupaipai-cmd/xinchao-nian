import test from 'node:test';
import assert from 'node:assert/strict';
import { applySatisfaction, newState } from '../src/engine.js';

const T = new Date('2026-10-26T06:00:00Z');

test('/v1/satisfy：只走乘法满足 + 饱足平台；不算她来了；同一个 eventId 不重复', () => {
  const s0 = newState(T);
  s0.drives.libido = 0.8;
  s0.drives.possess = 0.7;
  const before = s0.lastConversationAt;
  const { state, applied } = applySatisfaction(s0, ['libido', 'nope'], T, { eventId: 'e1' });
  assert.deepEqual(applied, ['libido']);
  assert.ok(state.drives.libido < 0.8 * 0.5);
  assert.equal(state.drives.possess, 0.7);                 // 想她不动
  assert.ok(state.satisfactionPlateaus.libido);
  assert.equal(state.lastConversationAt, before);          // 不算她来过
  const again = applySatisfaction(state, ['libido'], T, { eventId: 'e1' });
  assert.equal(again.duplicate, true);
  assert.equal(again.state.drives.libido, state.drives.libido);
});
