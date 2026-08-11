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
