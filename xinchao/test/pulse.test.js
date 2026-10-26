import test from 'node:test';
import assert from 'node:assert/strict';
import { bodyLine, breathLabel, computeVitals, normalizeOffset, sumOffsets } from '../src/pulse.js';
import { buildNowCompact } from '../src/context-envelope.js';
import { newState } from '../src/engine.js';

const T = new Date('2026-10-26T06:00:00Z');   // 北京 14:00

test('脉：醒着平静大约 60–80，睡着更慢，夹在 48–160', () => {
  const calm = computeVitals({ drives: {}, emotion: { arousal: 0.3, valence: 0.6 } }, T);
  assert.ok(calm.hr >= 60 && calm.hr <= 80, String(calm.hr));
  const asleep = computeVitals({ consciousness: 'sleeping', drives: {}, emotion: { arousal: 0.2, valence: 0.6 } }, T);
  assert.ok(asleep.hr < calm.hr);
  const wild = computeVitals({ drives: { libido: 1, anger: 1, possess: 1, grieve: 1 }, emotion: { arousal: 1, valence: 0 } }, T, { offsets: [{ hr: 80, breath: 20, until: T.getTime() + 60_000 }] });
  assert.ok(wild.hr <= 160 && wild.breath <= 35);
  assert.equal(wild.breathing, '急促');
});

test('脉：情欲、愤怒、唤醒都让心跳变快；同样的输入同样的结果', () => {
  const base = { drives: {}, emotion: { arousal: 0.35, valence: 0.5 } };
  const hot = { drives: { libido: 0.9 }, emotion: { arousal: 0.8, valence: 0.6 } };
  assert.ok(computeVitals(hot, T).hr > computeVitals(base, T).hr);
  assert.deepEqual(computeVitals(hot, T), computeVitals(hot, T));
});

test('偏移：过期的不算，范围夹住，要给 key 和 minutes', () => {
  const now = T.getTime();
  assert.deepEqual(sumOffsets([{ hr: 30, breath: 5, until: now - 1 }], now), { hr: 0, breath: 0 });
  assert.deepEqual(sumOffsets([{ hr: 500, breath: 99, until: now + 1 }], now), { hr: 80, breath: 20 });
  assert.ok(normalizeOffset({ hr: 10 }).error);
  assert.ok(normalizeOffset({ hr: 10, minutes: 5 }).error);
  const o = normalizeOffset({ key: 'run', hr: 30, breath: 4, minutes: 999 }, now);
  assert.equal(o.until, now + 180 * 60_000);
  const s = { drives: {}, emotion: { arousal: 0.35, valence: 0.5 } };
  assert.ok(computeVitals(s, T, { offsets: [o] }).hr > computeVitals(s, T).hr);
});

test('呼吸说法分五档', () => {
  assert.deepEqual([9, 12, 15, 20, 30].map(breathLabel), ['很深很长', '深长', '平稳', '偏浅', '急促']);
});

test('此刻块：脉那行只有整数，不会触发数字兜底；块满时脉那行先让位', () => {
  const state = newState(T);
  const line = bodyLine(computeVitals(state, T));
  assert.match(line, /^身体：心跳 \d+，呼吸/);
  const out = buildNowCompact(state, T, { body: line });
  assert.ok(out.ok);
  assert.ok(out.text.includes(line));
  assert.ok(!buildNowCompact(state, T).text.includes('身体：'));
});

test('此刻块的 digest：心跳数变、档位不变就不变', () => {
  const state = newState(T);
  const a = buildNowCompact(state, T, { body: '身体：心跳 72，呼吸平稳' });
  const b = buildNowCompact(state, T, { body: '身体：心跳 79，呼吸平稳' });
  const c = buildNowCompact(state, T, { body: '身体：心跳 95，呼吸平稳' });
  assert.equal(a.digest, b.digest);
  assert.notEqual(a.digest, c.digest);
});
