import assert from 'node:assert/strict';
import test from 'node:test';

import { applyConversationEvent, newState, settleState } from '../src/engine.js';
import { detectSelfSignals, renderNowLine } from '../src/self-signals.js';
import { scanAwareness } from '../src/awareness.js';

// 上海 14:00 起，避开凌晨冻结
const T0 = '2026-09-05T06:00:00.000Z';
const at = (h) => new Date(Date.parse(T0) + h * 3_600_000);
function baseState() {
  const state = newState(new Date(T0));
  state.lastSettledAt = T0; state.lastConversationAt = T0;
  return state;
}
const ev = (type, id) => ({ eventId: id, interactionType: type, sessionId: 's' });

test('drive peak fires once after 2h above 0.8, once per drive per day, and carries a now-line', () => {
  let state = baseState();
  state.drives.possess = 0.3;
  let r = detectSelfSignals(state, at(-1));                // 先见过它在低位
  state = r.state; state.drives.possess = 0.9;
  r = detectSelfSignals(state, at(0));
  assert.equal(r.signals.length, 0);                       // 刚过线，起点记下
  r = detectSelfSignals(r.state, at(1));
  assert.equal(r.signals.length, 0);
  r = detectSelfSignals(r.state, at(2.1));
  assert.equal(r.signals.length, 1);
  assert.equal(r.signals[0].kind, 'drive_peak');
  assert.match(r.signals[0].text, /此刻：想她（涌）/);
  assert.doesNotMatch(r.signals[0].text, /0\.\d|possess/);
  r = detectSelfSignals(r.state, at(3));
  assert.equal(r.signals.length, 0);                       // 当天不重复
  assert.equal(r.ttlHours, 2);
});

test('emotion shift: low held 30 min fires once, recovery fires once, 2h gap between', () => {
  let state = baseState();
  state = applyConversationEvent(state, ev('conflict', 'c1'), at(0)).state;
  state = applyConversationEvent(state, ev('conflict', 'c2'), at(0.01)).state;
  assert.ok(['低落', '烦躁'].includes(state.emotion.label), state.emotion.label);
  let r = detectSelfSignals(state, at(0.1));
  assert.equal(r.signals.length, 0);
  r = detectSelfSignals(r.state, at(0.6));
  assert.equal(r.signals.length, 1);
  assert.equal(r.signals[0].kind, 'emotion_shift');
  assert.match(r.signals[0].text, /争执/);
  r = detectSelfSignals(r.state, at(1));
  assert.equal(r.signals.length, 0);
  let recovered = r.state;
  recovered.emotion.valence = 0.8; recovered.emotion.arousal = 0.3; recovered.emotion.label = '安心';
  r = detectSelfSignals(recovered, at(1.5));
  assert.equal(r.signals.length, 0);                       // 2h 间隔未到
  r = detectSelfSignals(r.state, at(3));
  assert.equal(r.signals.length, 1);
  assert.equal(r.signals[0].subject, 'recover');
});

test('quiet hours and the daily cap block signals; wake residue fires once per dream', () => {
  let state = baseState();
  state.drives.possess = 0.9; state.drives.monitor = 0.9;
  let r = detectSelfSignals(state, at(0));
  const dawn = new Date('2026-09-05T19:30:00.000Z');       // 上海 03:30
  r = detectSelfSignals(r.state, dawn);
  assert.equal(r.signals.length, 0);
  const capped = baseState();
  capped.selfSignals = { dayUsage: { '2026-09-05': 8 } };
  capped.pendingAwareness = { dreamId: 'd1', residue: '海边有灯' };
  assert.equal(detectSelfSignals(capped, at(0)).signals.length, 0);
  const woke = baseState();
  woke.pendingAwareness = { dreamId: 'd1', residue: '海边有灯' };
  r = detectSelfSignals(woke, at(0));
  assert.equal(r.signals.length, 1);
  assert.equal(r.signals[0].kind, 'wake_residue');
  assert.match(r.signals[0].text, /海边有灯/);
  assert.equal(detectSelfSignals(r.state, at(0.5)).signals.length, 0);
});

test('awareness digest goes out once on the review day only', () => {
  let state = baseState();
  for (let d = 0; d < 5; d += 1) {
    state = applyConversationEvent(state, ev('conflict', `k${d}`), at(-24 * (5 - d))).state;
    state = settleState(state, at(-24 * (5 - d) + 3)).state;
  }
  state = applyConversationEvent(state, { eventId: 'wake', sessionId: 's' }, at(-0.1)).state;   // 醒着才递
  state = scanAwareness(state, at(0), { force: true }).state;
  assert.ok(state.awareness.candidates.length >= 1);
  // T0 = 2026-09-05 周六：默认复盘日是周日，不提
  assert.equal(detectSelfSignals(state, at(0)).signals.filter((s) => s.kind === 'awareness').length, 0);
  let r = detectSelfSignals(state, at(0), { awarenessReviewWeekday: 6 });
  const aw = r.signals.find((s) => s.kind === 'awareness');
  assert.ok(aw);
  assert.match(aw.text, /觉察/);
  assert.doesNotMatch(aw.text, /均值|次/);                    // 只说有几条，不念候选原文
  assert.equal(detectSelfSignals(r.state, at(1), { awarenessReviewWeekday: 6 }).signals.filter((s) => s.kind === 'awareness').length, 0);
  assert.match(renderNowLine(state, at(0)), /^此刻：/);
});

test('a drive parked at its ceiling is a flat line, not a surge: no drive_peak', () => {
  let state = baseState();
  state.drives.possess = 0.9;
  let r = detectSelfSignals(state, at(0));
  r = detectSelfSignals(r.state, at(3));
  r = detectSelfSignals(r.state, at(6));
  assert.equal(r.signals.filter((s) => s.kind === 'drive_peak').length, 0);
});

test('a promoted obsession is announced once', () => {
  let state = baseState();
  state.thoughtPool.obsessions.push({ key: 'possess', text: '她说的那句门是可以拉开的', intensity: 0.7, feedbacks: 0 });
  let r = detectSelfSignals(state, at(0));
  const ob = r.signals.find((s) => s.kind === 'obsession');
  assert.ok(ob);
  assert.match(ob.text, /门是可以拉开的/);
  assert.equal(detectSelfSignals(r.state, at(1)).signals.filter((s) => s.kind === 'obsession').length, 0);
});

test('drive peak signals carry a response hint: self-serve drives say how to report, relational ones say wait for her', async () => {
  const { responseHint, SELF_SERVE_DRIVES } = await import('../src/self-signals.js');
  assert.ok(SELF_SERVE_DRIVES.has('reflection'));
  assert.match(responseHint('reflection'), /xinchao_event/);
  assert.match(responseHint('share'), /sharing \/ reflection \/ task_progress \/ discovery/);
  assert.doesNotMatch(responseHint('possess'), /xinchao_event/);
  assert.match(responseHint('possess'), /等她回应/);
});
