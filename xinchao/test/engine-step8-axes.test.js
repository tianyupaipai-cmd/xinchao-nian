import assert from 'node:assert/strict';
import test from 'node:test';

import { newState, settleAndApplyConversationEvent, settleState } from '../src/engine.js';
import { buildNowCompact } from '../src/context-envelope.js';
import { emotionSummary } from '../src/emotion.js';
import { AXES } from '../src/core-axes.js';

// 10-03 驱力第 8 步：花蕊三根慢轴（安全感、自信、心境）。
const T0 = '2026-10-03T04:00:00.000Z';
const opts = { sleepAfterMinutes: 6000, settle: { timeZone: 'Asia/Shanghai' } };
const at = (h) => new Date(Date.parse(T0) + h * 3_600_000);
function base() { const s = newState(new Date(T0)); s.lastSettledAt = T0; s.lastConversationAt = T0; s.drives.favored = 0; s.drives.grieve = 0; return s; }
const ev = (s, id, type, h, extra = {}) => settleAndApplyConversationEvent(s, { sessionId: 'g', eventId: id, interactionType: type, ...extra }, at(h), opts).state;

test('slights and unreconciled fights wear security down; being soothed and making up bring it back', () => {
  let s = base();
  for (let i = 0; i < 4; i++) s = ev(s, `s${i}`, 'slighted', i * 0.1, { sub: '吃醋' });
  for (let i = 0; i < 3; i++) s = ev(s, `c${i}`, 'conflict', 0.5 + i * 0.1, { cause: '你根本不在乎' });
  const low = s.axes.security;
  assert.ok(low < AXES.baseline.security - 0.2, `security ${low}`);
  assert.match(buildNowCompact(s, at(1)).text, /底色：心里不太踏实/);
  s = ev(s, 'r', 'reconciliation', 1.2, { herWords: '好啦不生气了' });
  s = ev(s, 'a', 'intimacy', 1.3);
  assert.ok(s.axes.security > low + 0.08);
});

test('confidence: getting things done and being praised thickens it; self-blame thins it; low confidence keeps 得意 dark', () => {
  let s = base();
  for (let i = 0; i < 4; i++) s = ev(s, `t${i}`, 'task_progress', i * 1.1, { proof: ['her_ok', 'first', 'hard', 'her_ok'][i] });
  s = ev(s, 'p', 'affection', 0.5, { sub: '害羞', strength: 'heavy' });
  assert.ok(s.axes.confidence > AXES.baseline.confidence + 0.08);   // 10-14 同一天递减后：四件约 +0.07，加被夸 +0.03
  let d = base();
  for (let i = 0; i < 5; i++) d = ev(d, `z${i}`, 'loss', i * 0.1, { sub: '自责' });
  assert.ok(d.axes.confidence < 0.35, `confidence ${d.axes.confidence}`);
  d = ev(d, 'tt', 'task_progress', 0.6, { proof: 'her_ok' });
  assert.notEqual(emotionSummary(d, at(0.61)).shown, '得意');
});

test('left alone, both axes drift back toward their baseline over days', () => {
  let s = base(); s.axes = { security: 0.2, confidence: 0.9, at: T0 };
  s = settleState(s, at(72), 6000).state;
  assert.ok(Math.abs(s.axes.security - (AXES.baseline.security + (0.2 - AXES.baseline.security) / 2)) < 0.02, `${s.axes.security}`);
  assert.ok(s.axes.confidence < 0.9 && s.axes.confidence > AXES.baseline.confidence);
});

test('insecure: grief rises faster, and the emotion line can show 不安', () => {
  const calm = ev(base(), 'l1', 'loss', 0.1, { sub: '失落' });
  const shaky = base(); shaky.axes = { security: 0.2, confidence: 0.6, at: T0 };
  const s2 = ev(shaky, 'l2', 'loss', 0.1, { sub: '失落' });
  assert.ok(s2.drives.grieve > calm.drives.grieve * 1.2);
  const u = base(); u.axes = { security: 0.2, confidence: 0.6, at: T0 }; u.emotion.valence = 0.5;
  assert.equal(emotionSummary(u, at(0)).shown, '不安');
});

test('10-14 做成事的边界：只认 proof；自己报「做好了」不加分、不得意；同一天递减；被指出错要扣；高位减半', () => {
  // 自己宣布做好了（routine / 没带 proof）：不加自信，也不亮得意
  let r = base();
  for (let i = 0; i < 5; i++) r = ev(r, `r${i}`, 'task_progress', i * 1.5, i % 2 ? { proof: 'routine' } : {});
  assert.equal(r.axes.confidence, AXES.baseline.confidence);
  assert.notEqual(emotionSummary(r, at(6.1)).shown, '得意');
  // 她认可了：加分、亮得意
  let s = ev(base(), 'ok', 'task_progress', 0.1, { proof: 'her_ok' });
  assert.ok(Math.abs(s.axes.confidence - (AXES.baseline.confidence + 0.03)) < 0.002, `${s.axes.confidence}`);
  assert.equal(emotionSummary(s, at(0.2)).shown, '得意');
  // 她夸他做的东西常被判成亲昵：带了 proof 一样算
  const praised = ev(base(), 'pa', 'affection', 0.1, { proof: 'her_ok' });
  assert.ok(praised.axes.confidence > AXES.baseline.confidence + 0.02);
  // 同一天第 n 件 ×0.6^(n-1)：五件加起来远小于 5×0.03
  let day = base();
  for (let i = 0; i < 5; i++) day = ev(day, `d${i}`, 'task_progress', i * 2, { proof: 'her_ok' });
  const total = day.axes.confidence - AXES.baseline.confidence;
  assert.ok(total < 0.03 * (1 + 0.6 + 0.36 + 0.216 + 0.13) + 0.005 && total > 0.06, `day total ${total}`);
  // 被她指出错 / 返工：扣
  const slip = ev(base(), 'sl', 'companionship', 0.1, { slip: true });
  assert.ok(slip.axes.confidence < AXES.baseline.confidence - 0.035, `${slip.axes.confidence}`);
  // 已经高于 0.75：加分减半
  let hi = base(); hi.axes = { security: 0.62, confidence: 0.8, at: T0 };
  hi = ev(hi, 'x', 'task_progress', 0.1, { proof: 'hard' });
  assert.ok(hi.axes.confidence < 0.8 + 0.021, `halved above high: ${hi.axes.confidence}`);
});

test('10-14 自信没事时回得更快（半衰期 36 小时）', () => {
  let s = base(); s.axes = { security: 0.62, confidence: 0.9, at: T0 };
  s = settleState(s, at(36), 6000).state;
  assert.ok(Math.abs(s.axes.confidence - (AXES.baseline.confidence + 0.15)) < 0.02, `${s.axes.confidence}`);
});
