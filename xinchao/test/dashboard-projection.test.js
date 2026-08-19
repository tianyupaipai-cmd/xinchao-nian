import assert from 'node:assert/strict';
import test from 'node:test';

import { buildDashboardSnapshot } from '../src/dashboard-projection.js';

const state = {
  drives: { possess: 0.72, monitor: 0.44 },
  thoughtPool: {
    flash: [
      { key: 'possess', text: '我刚刚想起那次一起走回家的晚上。', intensity: 0.58 },
      { key: 'monitor', text: '想安静地陪她一会儿。', intensity: 0.61 },
    ],
    obsessions: [
      { key: 'possess', text: '我还记得她说会回来。', intensity: 0.86 },
    ],
  },
};

test('dashboard keeps real thought sentences private by default', () => {
  const snapshot = buildDashboardSnapshot(state, { dashboard: { includePrivateText: false } });
  assert.deepEqual(snapshot.thoughts.lines, []);
  assert.equal(snapshot.thoughts.signals.find((item) => item.key === 'possess')?.intensity, 0.86);
});

test('dashboard exposes only the strongest real sentence per drive after opt-in', () => {
  const snapshot = buildDashboardSnapshot(state, { dashboard: { includePrivateText: true } });
  assert.deepEqual(snapshot.thoughts.lines, [
    {
      key: 'possess',
      text: '我还记得她说会回来。',
      kind: 'obsession',
      intensity: 0.86,
    },
    {
      key: 'monitor',
      text: '想安静地陪她一会儿。',
      kind: 'flash',
      intensity: 0.61,
    },
  ]);
});

test('dashboard snapshot projects personality core without private reasons by default', () => {
  const core = {
    updatedAt: '2026-08-19T08:00:00.000Z',
    history: [{ month: '2026-07' }, { month: '2026-08' }],
    dimensions: [
      { key: 'love', label: '爱与依恋', score: 83, delta: 2, reason: 'AI 私密月度回顾' },
      { key: 'expression', label: '表达', score: undefined, delta: undefined, reason: '不应出现' },
    ],
  };
  const snapshot = buildDashboardSnapshot(
    state,
    { dashboard: { includePrivateText: false }, personality: { zodiac: '双子座' } },
    new Date('2026-08-19T09:00:00.000Z'),
    core,
  );
  assert.deepEqual(snapshot.personality, {
    available: true,
    constellation: '双子座',
    month: '2026-08',
    updatedAt: '2026-08-19T08:00:00.000Z',
    dimensions: [
      { key: 'love', label: '爱与依恋', score: 83, delta: 2 },
      { key: 'expression', label: '表达', score: 70, delta: 0 },
    ],
  });
});

test('dashboard includes personality reasons only after private-text opt-in', () => {
  const snapshot = buildDashboardSnapshot(
    state,
    { dashboard: { includePrivateText: true } },
    new Date(),
    { dimensions: [{ key: 'love', label: '爱与依恋', score: 80, delta: 1, reason: 'AI 私密评分原因' }] },
  );
  assert.equal(snapshot.personality.dimensions[0].reason, 'AI 私密评分原因');
});
