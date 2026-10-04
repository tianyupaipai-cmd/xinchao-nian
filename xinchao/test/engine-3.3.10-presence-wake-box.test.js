import assert from 'node:assert/strict';
import test from 'node:test';
import { mkdtemp } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { newState, settleAndApplyConversationEvent } from '../src/engine.js';
import { BlackBox } from '../src/black-box.js';

const T0 = new Date('2026-09-25T06:00:00.000Z');   // 北京 14:00
const at = (h) => new Date(T0.getTime() + h * 3_600_000);

function asleepSince(hoursAgo, now) {
  const s = newState(at(-10));
  s.consciousness = 'sleeping';
  s.sleepStartedAt = new Date(now.getTime() - hoursAgo * 3_600_000).toISOString();
  s.lastConversationAt = new Date(now.getTime() - (hoursAgo + 1.5) * 3_600_000).toISOString();
  s.lastSettledAt = now.toISOString();
  return s;
}

test('3.3.10 AI 自己回传、没带她原话的事件：不叫醒、不刷新"上次见她"、不记作息', () => {
  const now = at(13);   // 北京凌晨 3 点
  const before = asleepSince(4, now);
  const hist = [...before.arrivalHistogram];
  const r = settleAndApplyConversationEvent(before, { eventId: 'e1' }, now, { presence: false, recordArrival: true });
  assert.equal(r.state.consciousness, 'sleeping');
  assert.equal(r.state.lastConversationAt, before.lastConversationAt);
  assert.equal(r.state.pendingAwareness, null);
  assert.deepEqual(r.state.arrivalHistogram, hist);
});

test('3.3.10 她真的来了（默认 presence）：照常叫醒、记作息', () => {
  const now = at(0);
  const r = settleAndApplyConversationEvent(asleepSince(4, now), { eventId: 'e2' }, now, { recordArrival: true });
  assert.equal(r.state.consciousness, 'awake');
  assert.ok(r.state.pendingAwareness, '睡了 4 小时醒来算"刚醒"');
  assert.ok(r.state.arrivalHistogram.some((n) => n > 0));
});

test('3.3.10 白天走开一会儿（睡着不到 3 小时、没做梦）再回来：醒了，但不标"刚醒"', () => {
  const now = at(2);
  const r = settleAndApplyConversationEvent(asleepSince(1, now), { eventId: 'e3' }, now, { recordArrival: true });
  assert.equal(r.state.consciousness, 'awake');
  assert.equal(r.state.pendingAwareness, null);
});

test('3.3.10 作息按时间衰减：半衰期 7 天，隔一周再来，旧的只剩一半', () => {
  let s = newState(at(-200));
  s.arrivalHistogram[9] = 10; s.arrivalDecayAt = at(0).toISOString();
  s.lastConversationAt = at(-3).toISOString(); s.lastSettledAt = at(0).toISOString();
  const r = settleAndApplyConversationEvent(s, { eventId: 'a1' }, at(24 * 7), { recordArrival: true });
  assert.ok(Math.abs(r.state.arrivalHistogram[9] - 5) < 0.01, `应≈5，实际 ${r.state.arrivalHistogram[9]}`);
  assert.equal(r.state.arrivalDecayAt, at(24 * 7).toISOString());
});

test('3.3.10 匣子：到点提醒读了也一直露头；unpin 只取消提醒、条目留着', async () => {
  const box = new BlackBox(join(await mkdtemp(join(tmpdir(), 'box-')), 'black-box.json'));
  const due = await box.put({ text: '体检', remindAt: '2026-09-25T02:00:00.000Z' }, at(-10));
  const pinned = await box.put({ text: '一直想记着的', surface: true }, at(-10));
  await box.dueReminders(at(0));
  assert.equal((await box.surfaced(at(0))).length, 2);
  await box.read(due.id, at(0.1));
  await box.read(pinned.id, at(0.1));
  assert.equal((await box.surfaced(at(0.2))).length, 2, '读了提醒也还在，要烧掉或 unpin 才消');
  assert.equal(await box.unpin(due.id, at(0.3)), true);
  assert.deepEqual((await box.surfaced(at(0.4))).map((x) => x.id), [pinned.id]);
  assert.equal(await box.unpin(pinned.id, at(0.5)), true);
  assert.equal((await box.surfaced(at(0.6))).length, 0);
  assert.equal((await box.list(at(0.7))).length, 2, '条目都还在');
  assert.equal(await box.unpin('box-nope', at(0.8)), false);
});

test('3.3.10 此刻块：期待/挂念行不带强度数字，不会被兜底整块拦掉', async () => {
  const { buildNowCompact } = await import('../src/context-envelope.js');
  const now = new Date('2026-09-26T00:18:00.000Z');   // 北京 08:18
  const s = newState(new Date('2026-09-25T17:00:00.000Z'));
  s.arrivalHistogram = Array.from({ length: 24 }, () => 0.2); s.arrivalHistogram[8] = 9; s.arrivalHistogram[7] = 6;
  s.lastConversationAt = new Date('2026-09-25T17:53:00.000Z').toISOString(); s.lastSettledAt = now.toISOString();
  const r = buildNowCompact(s, now);
  assert.equal(r.ok, true, r.reason);
  assert.match(r.text, /期待：|挂念：/);
  assert.doesNotMatch(r.text, /\d\.\d/);
});
