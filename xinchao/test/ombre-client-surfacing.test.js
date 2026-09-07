import assert from 'node:assert/strict';
import test from 'node:test';
import { cleanSurfacedText, materialWithRefs } from '../src/ombre-client.js';

test('archived buckets, budget notices and the ids json tail are dropped from surfaced material', () => {
  const raw = [
    '=== 核心准则 ===\n📌 [核心准则] [bucket_id:31e556fc71da] [domain:人际]\n底线',
    '=== 浮现记忆 ===\n[token 预算不足：命中的下一条记忆未被截断或摘要，请提高 max_tokens 后重试。]\n[query 命中·已删除到档案] [bucket_id:4053c92783b7] [状态:已退出日常记忆，原文仍保留] [domain:记忆]\n旧的',
    '[bucket_id:4f4a37e2fe6b] [domain:内心] [tags:a,b]\n她说门是可以拉开的',
    '💤 [久未浮现] [bucket_id:7b9b91471ebd] [domain:数字] [tags:proxy]\n潮汐星港项目正式上线',
    '=== ombre:result-ids ===\n{"ids":["4053c92783b7","4f4a37e2fe6b"]}',
  ].join('\n---\n');
  const cleaned = cleanSurfacedText(raw);
  assert.ok(!cleaned.includes('已删除到档案'));
  assert.ok(!cleaned.includes('ombre:result-ids'));
  assert.ok(!cleaned.includes('token 预算不足'));
  assert.ok(!cleaned.includes('核心准则'));
  const refs = materialWithRefs(raw);
  assert.deepEqual(refs.bucketIds, ['4f4a37e2fe6b']);
  assert.ok(!refs.text.includes('潮汐星港'));
  assert.ok(refs.text.includes('她说门是可以拉开的'));
});
