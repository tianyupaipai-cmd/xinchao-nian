import assert from 'node:assert/strict';
import test from 'node:test';

import { newState, settleState, settleAndApplyConversationEvent } from '../src/engine.js';
import { buildNowCompact } from '../src/context-envelope.js';
import { DRIVE_KEYS } from '../src/dimensions.js';

// 10-02 驱力第 7 步：社交并进分享欲；好奇加「想了解她」；难过加「自责」。
const T0 = '2026-10-02T04:00:00.000Z';
const opts = { sleepAfterMinutes: 600, settle: { timeZone: 'Asia/Shanghai' } };
const at = (min) => new Date(Date.parse(T0) + min * 60_000);
function base() { const s = newState(new Date(T0)); s.lastSettledAt = T0; s.lastConversationAt = T0; return s; }
const ev = (s, id, type, m, extra = {}) =>
  settleAndApplyConversationEvent(s, { sessionId: 'g', eventId: id, interactionType: type, ...extra }, at(m), opts).state;

test('social is gone; an old save folds it into 分享欲 by taking the larger value', () => {
  assert.ok(!DRIVE_KEYS.includes('social'));
  const old = base(); old.drives.social = 0.47; old.drives.share = 0.30;
  const s = settleState(old, new Date(T0), 600).state;
  assert.equal(s.drives.social, undefined);
  assert.equal(s.drives.share, 0.47);
});

test('她说了半句 → 好奇（…·想了解她）; her telling relieves it a little', () => {
  let s = base(); s.drives.curiosity = 0.3;
  s = ev(s, 'i1', 'intrigued', 1, { sub: '想了解她' });
  assert.ok(s.drives.curiosity > 0.3);
  assert.match(buildNowCompact(s, at(2)).text, /好奇（[^）]*·想了解她）/);
  const peak = s.drives.curiosity;
  s = ev(s, 'i2', 'sharing', 3);
  assert.ok(s.drives.curiosity < peak);
});

test('自责 sits under 难过', () => {
  let s = base(); s.drives.grieve = 0;
  s = ev(s, 'z1', 'loss', 1, { sub: '自责' });
  assert.match(buildNowCompact(s, at(2)).text, /难过（[^）]*·自责）/);
});
