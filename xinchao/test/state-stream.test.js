import test from 'node:test';
import assert from 'node:assert/strict';
import { diffEvents } from '../src/state-stream.js';
import { newState } from '../src/engine.js';

const T = new Date('2026-10-26T06:00:00Z');

test('订阅推送：换档推一条、不给小数；1 分钟内同一股不重复；情绪、睡醒、满足各推一条', () => {
  const a = newState(T);
  a.drives.possess = 0.3;
  const b = structuredClone(a);
  b.drives.possess = 0.95;
  b.emotion = { ...(b.emotion ?? {}), label: '雀跃' };
  b.consciousness = 'sleeping';
  const lastSent = new Map();
  const evs = diffEvents(a, b, T, { lastSent, meta: { type: 'satisfy', details: { drives: ['libido'] } } });
  const types = evs.map((e) => e.type);
  assert.ok(types.includes('drive') && types.includes('emotion') && types.includes('sleep') && types.includes('satisfy'));
  const d = evs.find((e) => e.type === 'drive' && e.key === 'possess');
  assert.equal(d.level, '涌');
  assert.ok(!/\d\.\d/.test(JSON.stringify(evs.map(({ at, ...rest }) => rest))));   // 时间戳以外不带小数
  const again = diffEvents(a, b, new Date(T.getTime() + 30_000), { lastSent });
  assert.ok(!again.some((e) => e.type === 'drive' && e.key === 'possess'));
  assert.deepEqual(diffEvents(a, structuredClone(a), T), []);
});
