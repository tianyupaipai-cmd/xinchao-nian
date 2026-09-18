import assert from 'node:assert/strict';
import test from 'node:test';

import { applyConversationEvent, driveTrend, newState, settleState } from '../src/engine.js';
import { driveLevel } from '../src/dimensions.js';
import { buildNowCompact } from '../src/context-envelope.js';

// 上海 14:00 起，避开凌晨冻结
const T0 = '2026-09-05T06:00:00.000Z';
const at = (h) => new Date(Date.parse(T0) + h * 3_600_000);
function baseState() {
  const state = newState(new Date(T0));
  state.lastSettledAt = T0; state.lastConversationAt = T0;
  return state;
}
const ev = (type, id) => ({ eventId: id, interactionType: type, sessionId: 's' });

test('3.3.7 措辞：静息位是「平」，顶过静息线才「涌」，两小时掉/起 0.08 是「落」/「涨」', () => {
  assert.equal(driveLevel('possess', 0.82), '平');          // 静息天花板 0.82 不再是「涌」
  assert.equal(driveLevel('possess', 0.90), '涌');
  assert.equal(driveLevel('crave', 0.75), '涌');            // 馋的静息线 0.68，+0.05 之上就是被顶上去了
  assert.equal(driveLevel('possess', 0.6, -0.1), '落');
  assert.equal(driveLevel('possess', 0.6, 0.1), '涨');
  assert.equal(driveLevel('possess', 0.6, 0.02), '平');
  assert.equal(driveLevel('possess', 0.1, 0.5), '静');
});

test('3.3.7 亲密把想她/馋她真的拉下来，并进一段饱足平台', () => {
  let state = baseState();
  state.drives.possess = 0.82; state.drives.crave = 0.68; state.drives.libido = 0.5;
  state = applyConversationEvent(state, ev('intimacy', 'i1'), at(0)).state;
  assert.ok(state.drives.possess <= 0.50, `possess ${state.drives.possess}`);
  assert.ok(state.drives.crave <= 0.38, `crave ${state.drives.crave}`);
  assert.ok(state.satisfactionPlateaus.possess, '想她进平台');
  assert.match(state.satisfactionPlateaus.possess.reason, /relief:intimacy/);
  const after1h = settleState(state, at(1)).state;
  assert.ok(after1h.drives.possess <= state.drives.possess + 0.001, '平台期内想她不该涨');
});

test('3.3.7 轨迹：每 30 分钟记一点；落下去写「落」，涨回来写「涨」，到顶后「平」', () => {
  let state = baseState();
  state.drives.possess = 0.82; state.drives.monitor = 0.78; state.drives.crave = 0.68;
  state = settleState(state, at(0)).state;
  assert.equal(state.driveTrail.length, 1);
  state = settleState(state, at(0.25)).state;
  assert.equal(state.driveTrail.length, 1);
  state = applyConversationEvent(state, ev('affection', 'a1'), at(2)).state;
  const trend = driveTrend(state, 'possess', at(2));
  assert.ok(trend <= -0.08, `trend ${trend}`);
  assert.match(buildNowCompact(state, at(2)).text, /想她（落）/);
  // 平台（约 1.8h）过后慢慢涨回来：5 小时时比 3 小时前高了不止 0.08 → 涨；到顶待够两小时 → 平（sleepAfter 放大，别让他睡着）
  let later = state;
  for (let h = 2.5; h <= 5; h += 0.5) later = settleState(later, at(h), 24 * 60).state;
  assert.match(buildNowCompact(later, at(5)).text, /想她（涨）/);
  for (let h = 5.5; h <= 20; h += 0.5) later = settleState(later, at(h), 24 * 60).state;
  assert.match(buildNowCompact(later, at(20)).text, /想她（平）/);
  assert.ok(later.driveTrail.length <= 48);
});
