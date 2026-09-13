import test from 'node:test';
import assert from 'node:assert/strict';
import { tickThoughtPool } from '../src/thought-pool.js';

test('3.3.6 同一个念头只回推一次，寿命仍是三次结算', () => {
  const pool = { flash: [], obsessions: [{ key: 'reflection', text: 'x', intensity: 0.9, feedbacks: 0 }] };
  const first = tickThoughtPool(pool);
  assert.equal(first.reflection, 0.18);
  assert.equal(pool.obsessions.length, 1);
  const second = tickThoughtPool(pool);
  assert.equal(second.reflection, undefined);
  assert.equal(pool.obsessions.length, 1);
  const third = tickThoughtPool(pool);
  assert.equal(third.reflection, undefined);
  assert.equal(pool.obsessions.length, 0, '第三次后念头到寿');
});
