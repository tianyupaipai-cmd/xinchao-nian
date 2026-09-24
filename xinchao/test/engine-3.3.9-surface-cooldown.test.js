import assert from 'node:assert/strict';
import test from 'node:test';

import { newState, recentSurfacedBucketIds, recordSurfacedBuckets, surfacedDriveKey } from '../src/engine.js';
import { dropBuckets, materialWithRefs } from '../src/ombre-client.js';

const T0 = new Date('2026-09-24T06:00:00.000Z');
const at = (h) => new Date(T0.getTime() + h * 3_600_000);

test('3.3.9 同一段记忆 72 小时内算"最近浮现过"，过了就放出来', () => {
  let state = newState(T0);
  state = recordSurfacedBuckets(state, ['a', 'b'], T0);
  assert.deepEqual(recentSurfacedBucketIds(state, at(10)).sort(), ['a', 'b']);
  state = recordSurfacedBuckets(state, ['c'], at(50));
  assert.deepEqual(recentSurfacedBucketIds(state, at(73)), ['c']);          // a、b 已过 72h
  state = recordSurfacedBuckets(state, [], at(80));
  assert.deepEqual(Object.keys(state.surfacedBuckets), ['c']);              // 记录时顺手清掉过期的
});

test('3.3.9 浮现文本按桶剔除，开头的准则段保留，条数回到原来', () => {
  const text = '=== 核心准则 ===\n📌 [核心准则] [bucket_id:pin1] [domain:人际]\n准则一\n---\n=== 浮现记忆 ===\n[权重:7.2] [bucket_id:aa] [domain:人际,内心]\n第一段\n---\n[权重:5.1] [bucket_id:bb] [domain:成长]\n第二段\n---\n[权重:4.0] [bucket_id:cc] [domain:兴趣]\n第三段\n';
  const out = dropBuckets(text, ['aa'], 1);
  assert.ok(out.startsWith('=== 核心准则 ===') && out.includes('pin1'));   // 准则条目没权重，原样保留
  const refs = materialWithRefs(out);
  assert.deepEqual(refs.bucketIds, ['bb']);                               // 准则段在清洗时本来就去掉
  assert.deepEqual(refs.domains, ['成长']);
  assert.ok(!dropBuckets(text, ['aa', 'bb', 'cc'], 3).includes('[权重'));   // 全被剔掉：只剩准则，这轮没东西浮现
  assert.equal(dropBuckets(text, [], Infinity), text);
});

test('3.3.9 闪念不挂在已经涌的维上，改挂下一维；都在涌就还挂最高的', () => {
  const state = newState(T0);
  state.drives.reflection = 0.60;   // 静息线 0.42，已涌
  state.drives.possess = 0.70;      // 静息线 0.82，没涌
  assert.equal(surfacedDriveKey(['内心', '恋爱'], state), 'possess');
  state.drives.possess = 0.95;
  assert.equal(surfacedDriveKey(['内心', '恋爱'], state), 'crave');         // 想她也涌了 → 顺延到馋她
  for (const k of ['reflection', 'possess', 'crave', 'monitor', 'libido', 'grieve', 'share']) state.drives[k] = 0.95;
  assert.equal(surfacedDriveKey(['内心', '恋爱'], state), 'reflection');    // 全在涌 → 还挂最高的
  assert.equal(surfacedDriveKey(['内心', '恋爱']), 'reflection');           // 没有状态：按亲和度
});
