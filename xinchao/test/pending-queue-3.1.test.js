import assert from 'node:assert/strict';
import test from 'node:test';

import {
  addPending,
  dropPending,
  holdPending,
  markConsumed,
  markHoldSyncResult,
  selectForDelivery,
  selectForHoldSync,
  tickPending,
} from '../src/pending-queue.js';

const at = (hours) => new Date(Date.parse('2026-08-19T00:00:00.000Z') + hours * 3_600_000);

test('delivery status and user disposition remain orthogonal', () => {
  const state = { pending: [] };
  const item = addPending(state, { kind: 'share', content: '这句话想等她回来再说' }, at(0));
  markConsumed(state, [item.id], at(1));
  holdPending(state, [item.id], at(2));
  assert.equal(state.pending[0].status, 'consumed');
  assert.equal(state.pending[0].disposition, 'held');
  assert.equal(state.pending[0].holdSync.status, 'pending');
});

test('held unsaid items never expire and remain deliverable', () => {
  const state = { pending: [] };
  const item = addPending(state, { kind: 'reflection', content: '我当时想明白的一件事' }, at(0));
  holdPending(state, [item.id], at(1));
  tickPending(state, at(120));
  assert.equal(state.pending.length, 1);
  assert.deepEqual(selectForDelivery(state).map((entry) => entry.id), [item.id]);
});

test('consumed items keep a 24 hour user decision grace window', () => {
  const state = { pending: [] };
  const item = addPending(state, { kind: 'share', content: '说完后还可以决定留不留' }, at(0));
  markConsumed(state, [item.id], at(1));
  tickPending(state, at(24.9));
  assert.equal(state.pending.length, 1);
  tickPending(state, at(25.1));
  assert.equal(state.pending.length, 0);
});

test('drop immediately exits delivery without rewriting the delivery status', () => {
  const state = { pending: [] };
  const item = addPending(state, { kind: 'monitor', content: '这个不用说了' }, at(0));
  dropPending(state, [item.id], at(1));
  assert.equal(state.pending[0].status, 'pending');
  assert.equal(state.pending[0].disposition, 'dropped');
  assert.deepEqual(selectForDelivery(state), []);
  assert.deepEqual(selectForHoldSync(state), []);
});

test('OB hold failure remains held and retryable until a successful bucket id returns', () => {
  const state = { pending: [] };
  const item = addPending(state, { kind: 'reflection', content: '这件事值得留下' }, at(0));
  holdPending(state, [item.id], at(1));
  markHoldSyncResult(state, item.id, { ok: false, error: 'timeout' }, at(2));
  assert.equal(state.pending[0].disposition, 'held');
  assert.equal(state.pending[0].holdSync.status, 'retry');
  assert.deepEqual(selectForHoldSync(state).map((entry) => entry.id), [item.id]);

  markHoldSyncResult(state, item.id, { ok: true, ombreBucketId: 'bucket-saved' }, at(3));
  assert.equal(state.pending[0].ombreBucketId, 'bucket-saved');
  assert.equal(state.pending[0].holdSync.status, 'synced');
  assert.deepEqual(selectForHoldSync(state), []);
});
