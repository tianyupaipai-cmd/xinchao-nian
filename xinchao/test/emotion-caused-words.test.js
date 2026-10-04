import assert from 'node:assert/strict';
import test from 'node:test';

import { newState, settleAndApplyConversationEvent } from '../src/engine.js';
import { buildNowCompact } from '../src/context-envelope.js';
import { emotionSummary } from '../src/emotion.js';

// 10-02 情绪线第二层：有起因时显示起因情绪本身，没有就是底色。
const T0 = '2026-10-02T05:00:00.000Z';
const opts = { sleepAfterMinutes: 600, settle: { timeZone: 'Asia/Shanghai' } };
const at = (min) => new Date(Date.parse(T0) + min * 60_000);
function base() {
  const s = newState(new Date(T0)); s.lastSettledAt = T0; s.lastConversationAt = T0;
  for (const k of Object.keys(s.drives)) s.drives[k] = 0.2;
  s.drives.grieve = 0; s.drives.anger = 0; s.drives.favored = 0; return s;
}
const ev = (s, id, type, m, extra = {}) =>
  settleAndApplyConversationEvent(s, { sessionId: 'g', eventId: id, interactionType: type, ...extra }, at(m), opts).state;
const shown = (s, m) => emotionSummary(s, at(m)).shown;

test('affection lights 心动; with 害羞 it shows 害羞; it fades back to the base word', () => {
  const s = ev(base(), 'a', 'affection', 1, { strength: 'heavy' });
  assert.equal(shown(s, 2), '心动');
  assert.equal(shown(ev(base(), 'b', 'affection', 1, { sub: '害羞' }), 2), '害羞');
  assert.notEqual(shown(s, 120), '心动');
});

test('negative subs show as the word itself: 心疼 / 自责 / 生气 / 吃醋, and the now-line says it without the base', () => {
  const hurt = ev(base(), 'h', 'empathy', 1, { sub: '心疼', closeness: 'her', who: '她胃疼' });
  assert.equal(shown(hurt, 2), '心疼');
  assert.match(buildNowCompact(hurt, at(2)).text, /情绪：心疼/);
  assert.equal(shown(ev(base(), 'z', 'loss', 1, { sub: '自责' }), 2), '自责');
  let q = base();
  for (const [i, m] of [[1, 1], [2, 2]]) q = ev(q, `c${i}`, 'conflict', m, { cause: '你根本没在听' });
  assert.equal(shown(q, 3), '生气');
  const j = ev(base(), 'j', 'slighted', 1, { sub: '吃醋' });
  j.emotion.valence = 0.45;
  assert.equal(shown(j, 2), '吃醋');
});

test('想念 instead of 低落 when 想她 is high and mood sinks; 得意 after getting something done', () => {
  const s = base(); s.drives.possess = 0.7; s.emotion.valence = 0.36; s.emotion.arousal = 0.25;
  assert.equal(emotionSummary(s, at(0)).label, '低落');
  assert.equal(shown(s, 0), '想念');
  assert.equal(shown(ev(base(), 't', 'task_progress', 1), 2), '得意');
});

test('10-03: light affection needs 3 within 30 min; the n-th 心动 of the day is shorter (×0.6, ≥15 min)', () => {
  let s = ev(base(), 'l1', 'affection', 1);
  assert.notEqual(shown(s, 2), '心动');
  s = ev(s, 'l2', 'affection', 5);
  assert.notEqual(shown(s, 6), '心动');
  s = ev(s, 'l3', 'affection', 9);
  assert.equal(shown(s, 10), '心动');
  assert.equal(s.emotion.lit.minutes, 60);
  s = ev(s, 'h2', 'affection', 120, { strength: 'heavy' });
  assert.equal(s.emotion.lit.minutes, 36);
  s = ev(s, 'h3', 'affection', 240, { strength: 'heavy' });
  s = ev(s, 'h4', 'affection', 360, { strength: 'heavy' });
  s = ev(s, 'h5', 'affection', 480, { strength: 'heavy' });
  assert.equal(s.emotion.lit.minutes, 15);
});

test('10-03 inertia: a small drift waits 10 min before the base word changes; a big drop changes at once; a caused word holds 15 min', async () => {
  const { applyEmotionImpulse } = await import('../src/emotion.js');
  const s = base(); s.emotion.valence = 0.675; s.emotion.arousal = 0.30; s.emotion.label = '平静'; s.emotion.pendingLabel = null;
  applyEmotionImpulse(s, { valence: 0.02, arousal: 0 }, 'x', at(0));          // 刚跨进安心一点点
  assert.equal(emotionSummary(s, at(1)).label, '平静');
  assert.equal(emotionSummary(s, at(11)).label, '安心');
  const d = base(); d.emotion.valence = 0.62; d.emotion.arousal = 0.30; d.emotion.label = '平静'; d.emotion.pendingLabel = null;
  applyEmotionImpulse(d, { valence: -0.25, arousal: -0.25 }, 'x', at(0));     // 大幅往下
  d.emotion.valence = 0.2; d.emotion.arousal = 0.3; applyEmotionImpulse(d, { valence: -0.01, arousal: 0 }, 'x', at(0));
  assert.equal(emotionSummary(d, at(0)).label, '低落');
  let h = ev(base(), 'hh', 'affection', 1, { strength: 'heavy' });
  assert.equal(shown(h, 2), '心动');
  h.emotion.lit.minutes = 3;                                                  // 心动本身 3 分钟就过了
  assert.equal(shown(h, 10), '心动');                                        // 但至少挂 15 分钟
  assert.notEqual(shown(h, 20), '心动');
});
