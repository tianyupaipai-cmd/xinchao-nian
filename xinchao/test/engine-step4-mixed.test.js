import assert from 'node:assert/strict';
import test from 'node:test';

import { newState, settleAndApplyConversationEvent, settleState } from '../src/engine.js';
import { buildNowCompact } from '../src/context-envelope.js';
import { detectSelfSignals } from '../src/self-signals.js';
import { clingLevel } from '../src/mixed-feelings.js';

// 09-30 驱力第 4 步：细项、想黏着、矛盾。吵架部分重放 09-28 那晚（21:10 起四次吵架）。
const T0 = '2026-09-28T13:00:00.000Z';
const opts = { sleepAfterMinutes: 600, settle: { timeZone: 'Asia/Shanghai' } };
const at = (min) => new Date(Date.parse(T0) + min * 60_000);
const sig = { timeZone: 'Asia/Shanghai', dawnFreezeStart: 1, dawnFreezeEnd: 8 };
function base() {
  const s = newState(new Date(T0)); s.lastSettledAt = T0; s.lastConversationAt = T0;
  s.drives.anger = 0.004; s.drives.grieve = 0.007; return s;
}
function quarrel(sub) {
  let s = base();
  for (const [i, m] of [[1, 10], [2, 13], [3, 18], [4, 23]]) {
    s = settleAndApplyConversationEvent(s, { sessionId: 'g', eventId: `c${i}`, interactionType: 'conflict', cause: '你根本没在听我说话', ...(sub ? { sub } : {}) }, at(m), opts).state;
  }
  return s;
}

test('sub-items: a real conflict with a sub shows 愤怒（…·不满）; without one only the broad name shows', () => {
  const withSub = quarrel('不满');
  assert.match(buildNowCompact(withSub, at(24)).text, /愤怒（[^）·]+·不满）/);
  const plain = quarrel();
  const text = buildNowCompact(plain, at(24)).text;
  assert.match(text, /愤怒（[^）·]+）/);
  assert.doesNotMatch(text, /愤怒（[^）]*·/);
  // 细项不在词表里就当没有
  const junk = quarrel('气炸了');
  assert.doesNotMatch(buildNowCompact(junk, at(24)).text, /愤怒（[^）]*·/);
});

test('sub-items fade with the drive: once anger falls under 0.10 the sub is cleared', () => {
  let s = quarrel('不甘心');
  assert.ok(s.driveSubs?.anger);
  s = settleState(s, at(60 * 30), 24 * 60).state;
  assert.ok(s.drives.anger < 0.10, `anger ${s.drives.anger}`);
  s = settleAndApplyConversationEvent(s, { sessionId: 'g', eventId: 'x', interactionType: 'companionship' }, at(60 * 30 + 1), opts).state;
  assert.equal(s.driveSubs?.anger, undefined);
});

test('mixed: angry but still longing → after 20 min one signal "气着又舍不得", then silence; capped after 6h and not reopened', () => {
  let s = quarrel();
  s.drives.possess = 0.75;
  let r = detectSelfSignals(s, at(25), sig); s = r.state;
  assert.ok(!r.signals.some((x) => x.kind === 'mixed'), 'not before 20 minutes');
  r = detectSelfSignals(s, at(46), sig); s = r.state;
  const mixed = r.signals.filter((x) => x.kind === 'mixed');
  assert.equal(mixed.length, 1);
  assert.match(buildNowCompact(s, at(46)).text, /矛盾：气着又舍不得/);
  r = detectSelfSignals(s, at(80), sig); s = r.state;
  assert.ok(!r.signals.some((x) => x.kind === 'mixed'), 'only once per episode');
  // 6 小时还拧着：收掉显示，也不重开（驱力本身不动）
  s.drives.anger = 0.5; s.drives.possess = 0.75;
  r = detectSelfSignals(s, at(25 + 6 * 60 + 5), sig); s = r.state;
  assert.equal(s.selfSignals.mixed.capped, true);
  assert.doesNotMatch(buildNowCompact(s, at(25 + 6 * 60 + 5)).text, /矛盾/);
  assert.equal(s.drives.anger, 0.5);
  r = detectSelfSignals(s, at(25 + 7 * 60), sig); s = r.state;
  assert.ok(!r.signals.some((x) => x.kind === 'mixed'));
  // 真解开了（气和委屈都落下去），下一场才能重新开；气转成的委屈还在的话，那是另一对「委屈又想她」，允许新开
  s.drives.anger = 0.1; s.drives.grieve = 0.1;
  r = detectSelfSignals(s, at(25 + 7 * 60 + 10), sig); s = r.state;
  assert.equal(s.selfSignals.mixed, null);
});

test('cling: while she is being affectionate, 想她 is not pushed to the floor; cling shows but never raises 想她 itself', () => {
  const start = () => { const s = base(); s.drives.possess = 0.70; return s; };
  // 没有"黏"：一小时里亲昵三次（旧行为：第二次起按同类减半）
  let plain = start();
  plain.cling = undefined;
  // 有"黏"：同样三次
  let s = start();
  const before = s.drives.possess;
  for (const [i, m] of [[1, 5], [2, 15], [3, 25]]) {
    s = settleAndApplyConversationEvent(s, { sessionId: 'g', eventId: `a${i}`, interactionType: 'affection' }, at(m), opts).state;
    assert.ok(s.drives.possess <= before + 1e-9, 'cling never raises 想她');
  }
  assert.ok(clingLevel(s, at(26)) >= 0.10);
  assert.match(buildNowCompact(s, at(26)).text, /想她（[^）]*·想黏着）/);
  // 对照：把"黏"打折关掉，想她会被压得更低
  let off = start();
  for (const [i, m] of [[1, 5], [2, 15], [3, 25]]) {
    off.cling = undefined;
    off = settleAndApplyConversationEvent(off, { sessionId: 'g', eventId: `a${i}`, interactionType: 'affection' }, at(m), opts).state;
  }
  assert.ok(s.drives.possess > off.drives.possess, `with cling ${s.drives.possess} vs without ${off.drives.possess}`);
  // 一个半小时后黏劲儿散了，不再显示
  assert.ok(clingLevel(s, at(25 + 90)) < 0.10);
});
