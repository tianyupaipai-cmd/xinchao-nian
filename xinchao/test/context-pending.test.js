import assert from 'node:assert/strict';
import test from 'node:test';

import { buildContextEnvelope } from '../src/context-envelope.js';
import { addPending } from '../src/pending-queue.js';
import { newState } from '../src/engine.js';

test('context carries first-person pending output with opaque ids for delivery receipts', () => {
  const now = new Date('2026-08-19T08:00:00.000Z');
  const state = newState(now);
  addPending(state, { id: 'pending_one', kind: 'share', content: '下午我翻到一本想跟她说的书。' }, now);
  const envelope = buildContextEnvelope({ state, sessionId: 'session-a', now });
  const section = envelope.sections.find((item) => item.id === 'pending_from_me');
  assert.ok(section);
  assert.equal(section.content, '下午我翻到一本想跟她说的书。');
  assert.deepEqual(section.data.ids, ['pending_one']);
});
