import { applySurfacedThought, surfacedDriveKey } from '../src/engine.js';
import assert from 'node:assert/strict';
import test from 'node:test';

import { applyOutputReflux, newState } from '../src/engine.js';
import { addFlashThought, newThoughtPool, tickThoughtPool } from '../src/thought-pool.js';

test('output reflux keeps source OB references without breaking the old call shape', () => {
  const state = newState(new Date('2026-08-19T08:00:00.000Z'));
  const oldStyle = applyOutputReflux(state, 'share', '想告诉她一件事');
  assert.equal(oldStyle.applied, true);
  assert.equal(oldStyle.state.thoughtPool.flash[0].ombreBucketId, null);
  assert.deepEqual(oldStyle.state.thoughtPool.flash[0].sourceOmbreBucketIds, []);

  const bound = applyOutputReflux(
    state,
    'share',
    '想告诉她一件事',
    new Date('2026-08-19T08:05:00.000Z'),
    0.3,
    { sourceOmbreBucketIds: ['bucket-a', 'bucket-b'] },
  );
  assert.equal(bound.state.thoughtPool.flash[0].ombreBucketId, 'bucket-a');
  assert.deepEqual(bound.state.thoughtPool.flash[0].sourceOmbreBucketIds, ['bucket-a', 'bucket-b']);
});

test('a promoted obsession keeps the concrete memory it grew from', () => {
  const pool = newThoughtPool();
  addFlashThought(pool, 'possess', '记得那句话', 1, {
    ombreBucketId: 'bucket-origin',
    sourceOmbreBucketIds: ['bucket-origin', 'bucket-related'],
  });
  tickThoughtPool(pool);
  tickThoughtPool(pool);
  tickThoughtPool(pool);
  assert.equal(pool.obsessions.length, 1);
  assert.equal(pool.obsessions[0].ombreBucketId, 'bucket-origin');
  assert.deepEqual(pool.obsessions[0].sourceOmbreBucketIds, ['bucket-origin', 'bucket-related']);
});

test('surfaced memories seed flash thoughts and repeated surfacing reinforces the same drive', () => {
  let state = newState(new Date('2026-09-05T08:00:00.000Z'));
  assert.equal(surfacedDriveKey(['家庭']), 'grieve');
  assert.equal(surfacedDriveKey(['恋爱', '亲密']), 'libido');
  let r = applySurfacedThought(state, 'possess', '她说门是可以拉开的', new Date());
  assert.equal(r.seeded, true);
  assert.equal(r.state.thoughtPool.flash.at(-1).intensity, 0.45);
  r = applySurfacedThought(r.state, 'possess', '她说门是可以拉开的', new Date());
  assert.equal(r.seeded, false);
  assert.ok(r.state.thoughtPool.flash.at(-1).intensity > 0.8);
  assert.equal(applySurfacedThought(r.state, 'nope', 'x').changed, false);
});
