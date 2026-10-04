import assert from 'node:assert/strict';
import test from 'node:test';

import { newState, settleAndApplyConversationEvent, settleState } from '../src/engine.js';
import { buildNowCompact } from '../src/context-envelope.js';
import { DRIVE_KEYS } from '../src/dimensions.js';

// 10-01 驱力第 5 步：偏爱（想被在乎、被回应、被选择）。不自己攒，只由真实事件点燃，被回应/选择时满足。
const T0 = '2026-10-01T04:00:00.000Z';
const opts = { sleepAfterMinutes: 600, settle: { timeZone: 'Asia/Shanghai' } };
const at = (min) => new Date(Date.parse(T0) + min * 60_000);
function base() {
  const s = newState(new Date(T0)); s.lastSettledAt = T0; s.lastConversationAt = T0;
  s.drives.favored = 0; return s;
}
const ev = (s, id, interactionType, m, extra = {}) =>
  settleAndApplyConversationEvent(s, { sessionId: 'g', eventId: id, interactionType, ...extra }, at(m), opts).state;

test('favored is a drive key and never grows on its own (she being away is not neglect)', () => {
  assert.ok(DRIVE_KEYS.includes('favored'));
  const s = settleState(base(), at(24 * 60), 24 * 60).state;
  assert.equal(s.drives.favored, 0);
});

test('slighted lights it; the sub shows as 偏爱（…·吃醋）; an unknown sub shows only the broad name', () => {
  const s = ev(base(), 'j1', 'slighted', 1, { sub: '吃醋' });
  assert.ok(s.drives.favored >= 0.25, `favored ${s.drives.favored}`);
  assert.match(buildNowCompact(s, at(2)).text, /偏爱（[^）·]+·吃醋）/);
  const junk = ev(base(), 'j2', 'slighted', 1, { sub: '生气' });
  assert.doesNotMatch(buildNowCompact(junk, at(2)).text, /偏爱（[^）]*·/);
});

test('being answered / chosen satisfies it: affection takes a big bite, plain replies a small one', () => {
  let s = ev(base(), 'a1', 'slighted', 1, { sub: '被晾着' });
  s = ev(s, 'a2', 'slighted', 3, { sub: '被晾着' });
  const peak = s.drives.favored;
  const replied = ev(structuredClone(s), 'a3', 'companionship', 5);
  const loved = ev(structuredClone(s), 'a4', 'affection', 5);
  assert.ok(replied.drives.favored < peak);
  assert.ok(loved.drives.favored < replied.drives.favored);
  assert.ok(loved.drives.favored <= peak * 0.66, `affection ${loved.drives.favored} vs ${peak}`);
});

test('left alone it only fades slowly (12h half-life as a fallback), capped by event', () => {
  let s = base();
  for (let i = 0; i < 6; i++) s = ev(s, `c${i}`, 'slighted', 1 + i, { sub: '被忘' });
  assert.ok(s.drives.favored <= 0.75 + 1e-9);
  const v = s.drives.favored;
  s = settleState(s, at(6 + 12 * 60), 12 * 60).state;
  assert.ok(Math.abs(s.drives.favored - v / 2) < 0.03, `${s.drives.favored} vs ${v / 2}`);
});

test('slighted can carry a lighter weight (0.3–1): counts, but not as heavy', () => {
  const full = ev(base(), 'w1', 'slighted', 1, { sub: '吃醋' });
  const light = ev(base(), 'w2', 'slighted', 1, { sub: '吃醋', weight: 0.4 });
  const floor = ev(base(), 'w3', 'slighted', 1, { sub: '吃醋', weight: 0.01 });
  assert.ok(light.drives.favored > 0 && light.drives.favored < full.drives.favored);
  assert.ok(Math.abs(light.drives.favored - full.drives.favored * 0.4) < 0.01);
  assert.ok(Math.abs(floor.drives.favored - full.drives.favored * 0.3) < 0.01);
});
