import assert from 'node:assert/strict';
import test from 'node:test';

import { applyConversationEvent, newState } from '../src/engine.js';
import { emotionCoords, stampEmotionArgs } from '../src/emotion.js';

const T0 = new Date('2026-09-05T08:00:00.000Z');

test('breath calls get the current emotion coordinates unless the caller gave their own', () => {
  const state = newState(T0);
  const stamped = stampEmotionArgs('breath', { query: 'x' }, state);
  assert.equal(stamped.stamped, true);
  assert.deepEqual({ valence: stamped.args.valence, arousal: stamped.args.arousal }, emotionCoords(state));
  assert.equal(stamped.args.query, 'x');
  const own = stampEmotionArgs('breath', { query: 'x', valence: 0.2, arousal: 0.9 }, state);
  assert.equal(own.stamped, false);
  assert.equal(own.args.valence, 0.2);
  const sentinel = stampEmotionArgs('breath', { query: 'x', valence: -1, arousal: -1 }, state);
  assert.equal(sentinel.stamped, true);
});

test('hold is stamped only when the mood clearly leaves neutral; grow is never touched', () => {
  const calm = newState(T0);
  assert.equal(stampEmotionArgs('hold', { content: 'a' }, calm).stamped, false);
  const upset = applyConversationEvent(calm, { eventId: 'c', interactionType: 'conflict', sessionId: 's' }, T0).state;
  const stamped = stampEmotionArgs('hold', { content: 'a' }, upset);
  assert.equal(stamped.stamped, true);
  assert.ok(stamped.args.valence < 0.5);
  assert.equal(stampEmotionArgs('grow', { items: [] }, upset).stamped, false);
});
