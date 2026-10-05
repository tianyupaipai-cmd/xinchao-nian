import assert from 'node:assert/strict';
import test from 'node:test';

import { newState, settleAndApplyConversationEvent } from '../src/engine.js';
import { buildDashboardSnapshot } from '../src/dashboard-projection.js';

const T0 = '2026-10-03T12:00:00.000Z';
const at = (m) => new Date(Date.parse(T0) + m * 60_000);
const ev = (s, id, type, m, extra = {}) => settleAndApplyConversationEvent(s, { sessionId: 'g', eventId: id, interactionType: type, ...extra }, at(m), { sleepAfterMinutes: 600 }).state;

test('caused emotions leave marks for the tide band; her words only reach the dashboard when private text is on', () => {
  let s = newState(new Date(T0)); s.lastSettledAt = T0;
  s = ev(s, 'a', 'affection', 1, { strength: 'heavy', note: '你还在就好' });
  s = ev(s, 'b', 'empathy', 2, { sub: '心疼', closeness: 'her', who: '她', note: '今天胃好疼' });
  s = ev(s, 'c', 'companionship', 3);
  const words = s.emotionMarks.map((m) => m.word);
  assert.deepEqual(words, ['心动', '心疼']);
  const pub = buildDashboardSnapshot(s, {}, at(4));
  assert.equal(pub.emotion.marks.length, 2);
  assert.equal(pub.emotion.marks[0].why, '她亲近你');
  const priv = buildDashboardSnapshot(s, { dashboard: { includePrivateText: true } }, at(4));
  assert.equal(priv.emotion.marks[1].why, '今天胃好疼');
  assert.ok('stamen' in pub && 'mixed' in pub);
});

test('mark-only events leave a mark (optionally back-dated) without moving any drive', () => {
  let s = newState(new Date(T0)); s.lastSettledAt = T0;
  const before = { ...s.drives };
  s = ev(s, 'm1', 'intimacy', 5, { markOnly: true, strength: 'light', markAt: at(-60).toISOString(), note: '抱抱' });
  assert.equal(s.emotionMarks.length, 1);
  assert.equal(s.emotionMarks[0].word, '心动');
  assert.equal(s.emotionMarks[0].at, at(-60).toISOString());
  for (const k of Object.keys(before)) assert.ok(Math.abs(s.drives[k] - before[k]) < 0.02, k);
});

test('the same feeling coming again within 2 hours merges into one mark with a count', async () => {
  const { recordMark, recentMarks } = await import('../src/emotion-marks.js');
  const s = {};
  recordMark(s, '心动', 3, { type: 'intimacy', note: '第一句' }, at(0));
  recordMark(s, '心动', 2, { type: 'affection', note: '第二句' }, at(50));
  recordMark(s, '害羞', 2, {}, at(60));
  recordMark(s, '心动', 2, { note: '第三句' }, at(160));   // 离上一次心动 110 分钟：还并
  recordMark(s, '心动', 2, {}, at(300));                   // 离上一次心动 140 分钟：新记一个
  assert.deepEqual(s.emotionMarks.map((m) => [m.word, m.n ?? 1]), [['心动', 3], ['害羞', 1], ['心动', 1]]);
  assert.equal(s.emotionMarks[0].weight, 3);
  assert.equal(s.emotionMarks[0].note, '第三句');
  assert.equal(s.emotionMarks[0].lastAt, at(160).toISOString());
  const pub = recentMarks(s, at(310));
  assert.equal(pub[0].n, 3);
  assert.equal(pub[1].n, undefined);
});
