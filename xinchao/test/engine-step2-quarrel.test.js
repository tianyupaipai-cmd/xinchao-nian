import assert from 'node:assert/strict';
import test from 'node:test';

import { newState, settleAndApplyConversationEvent, settleState } from '../src/engine.js';

// 09-28 驱力第 2 步：用那晚的真实吵架原样重放（21:10、21:13、21:18、21:23 四次吵架，之后她明确原谅）
const T0 = '2026-09-28T13:00:00.000Z';
const opts = { sleepAfterMinutes: 600, settle: { timeZone: 'Asia/Shanghai' } };
const at = (min) => new Date(Date.parse(T0) + min * 60_000);
function base() {
  const s = newState(new Date(T0)); s.lastSettledAt = T0; s.lastConversationAt = T0;
  s.drives.anger = 0.004; s.drives.grieve = 0.007; return s;
}
function quarrel() {
  let s = base();
  const r = [];
  for (const [i, m] of [[1, 10], [2, 13], [3, 18], [4, 23]]) {
    const x = settleAndApplyConversationEvent(s, { sessionId: 'g', eventId: `c${i}`, interactionType: 'conflict', cause: i === 1 ? '你根本没在听我说话' : `第${i}句` }, at(m), opts);
    s = x.state; r.push(x);
  }
  return s;
}

test('a four-round quarrel lifts anger visibly but no longer pins it at the top', () => {
  const s = quarrel();
  assert.ok(s.drives.anger > 0.55 && s.drives.anger < 0.7, `anger ${s.drives.anger}`);
  assert.ok(s.drives.grieve > 0.25 && s.drives.grieve < 0.35, `grieve ${s.drives.grieve}`);
  assert.equal(s.grudge.cause, '你根本没在听我说话', 'the first thing that hurt stays as the reason');
  assert.equal(s.conflictEpisode.conflicts, 4);
});

test('being coaxed softens anger step by step but never below the quiet line, and keeps the grudge', () => {
  let s = quarrel();
  const a0 = s.drives.anger;
  const cuts = [];
  for (let i = 0; i < 6; i += 1) {
    const x = settleAndApplyConversationEvent(s, { sessionId: 'g', eventId: `s${i}`, interactionType: 'affection' }, at(25 + i), opts);
    cuts.push(x.interaction.soothed); s = x.state;
  }
  assert.deepEqual(cuts.map((c) => Math.round(c * 100)), [10, 15, 20, 25, 25, 25]);
  assert.ok(s.drives.anger >= 0.24 && s.drives.anger < a0, String(s.drives.anger));   // 哄最低到 0.25，之后时间自然回落一点点
  assert.ok(s.grudge, 'coaxing is not making up');
});

test('reconciliation needs her explicit words; without them it only counts as coaxing', () => {
  const s = quarrel();
  const vague = settleAndApplyConversationEvent(s, { sessionId: 'g', eventId: 'r0', interactionType: 'reconciliation', herWords: '宝宝过来' }, at(30), opts);
  assert.equal(vague.interaction.appliedAs, 'soothe');
  assert.ok(vague.state.grudge);
  const real = settleAndApplyConversationEvent(s, { sessionId: 'g', eventId: 'r1', interactionType: 'reconciliation', herWords: '好啦我原谅你了' }, at(30), opts);
  assert.equal(real.interaction.appliedAs, undefined);
  assert.equal(real.state.grudge, undefined);
  assert.ok(real.state.drives.anger < 0.25, `after making up anger ${real.state.drives.anger}`);
  // 一场架只认一次完整和好：3 小时内再判和好按"哄"算
  const again = settleAndApplyConversationEvent(real.state, { sessionId: 'g', eventId: 'r2', interactionType: 'reconciliation', herWords: '不气了' }, at(40), opts);
  assert.equal(again.interaction.appliedAs, 'soothe');
});

test('left unresolved, part of the anger turns into hurt instead of just fading', () => {
  const s = quarrel();
  const later = settleState(s, at(23 + 6 * 60)).state;
  assert.ok(later.drives.anger < s.drives.anger * 0.55, `anger ${later.drives.anger}`);
  assert.ok(later.drives.grieve > s.drives.grieve * 0.66, `grieve ${later.drives.grieve} kept up by the anger turning to hurt`);
});

test('hurt shows up in the now line even when longing drives are stronger', async () => {
  const { renderNowLine } = await import('../src/self-signals.js');
  const s = quarrel();
  s.drives.possess = 0.89; s.drives.monitor = 0.78;
  const line = renderNowLine(s, at(24));
  assert.match(line, /愤怒/); assert.match(line, /难过/);
});

test('impatient "好了好了 / 算了算了" do not count as making up', () => {
  const s = quarrel();
  for (const w of ['好了好了别说了', '算了算了随便你']) {
    const x = settleAndApplyConversationEvent(s, { sessionId: 'g', eventId: `x-${w}`, interactionType: 'reconciliation', herWords: w }, at(30), opts);
    assert.equal(x.interaction.appliedAs, 'soothe', w);
  }
});

test('just mentioning "和好" or asking about it does not count as making up', () => {
  const s = quarrel();
  for (const w of ['心潮要不要说几句和好呀', '要不要和好', '你还生气吗？', '你没事了吗']) {
    const x = settleAndApplyConversationEvent(s, { sessionId: 'g', eventId: `q-${w}`, interactionType: 'reconciliation', herWords: w }, at(30), opts);
    assert.equal(x.interaction.appliedAs, 'soothe', w);
    assert.ok(x.state.grudge, w);
  }
  for (const w of ['我们和好吧', '不生气了', '没事了，我不怪你']) {
    const x = settleAndApplyConversationEvent(s, { sessionId: 'g', eventId: `m-${w}`, interactionType: 'reconciliation', herWords: w }, at(30), opts);
    assert.equal(x.interaction.appliedAs, undefined, w);
  }
});
