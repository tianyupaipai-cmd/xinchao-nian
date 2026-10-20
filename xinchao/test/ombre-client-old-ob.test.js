// 4.1.1：连的 OB 没有 breath_advanced（一起打包的内置版就没有）时，报错不能当记忆原文，要退回 breath。
import assert from 'node:assert/strict';
import test from 'node:test';
import { OmbreClient, OmbreToolError } from '../src/ombre-client.js';

function fakeOb({ hasAdvanced }) {
  const calls = [];
  const client = new OmbreClient({ url: 'http://ob.test/mcp', breathMaxResults: 3 });
  client.stateless = true;   // 跳过握手
  client.post = async (payload) => {
    const { name, arguments: args } = payload.params;
    calls.push({ name, args });
    if (name === 'breath_advanced' && !hasAdvanced) {
      return { jsonrpc: '2.0', id: 1, result: { isError: true, content: [{ type: 'text', text: 'Unknown tool: breath_advanced' }] } };
    }
    return { jsonrpc: '2.0', id: 1, result: { content: [{ type: 'text', text: '[bucket_id:4f4a37e2fe6b] [domain:内心]\n她说门是可以拉开的' }] } };
  };
  return { client, calls };
}

test('没有 breath_advanced：白天浮现退回 breath（不带日期和 with_ids），报错原文不进材料', async () => {
  const { client, calls } = fakeOb({ hasAdvanced: false });
  const m = await client.daytimeMaterialWithRefs([], null, new Date('2026-10-20T08:00:00Z'));
  assert.ok(!m.text.includes('Unknown tool'));
  assert.ok(m.text.includes('她说门是可以拉开的'));
  assert.deepEqual(calls.map((c) => c.name), ['breath_advanced', 'breath']);
  assert.equal(calls[1].args.date_from, undefined);
  assert.equal(calls[1].args.with_ids, undefined);
  assert.equal(calls[1].args.query, undefined);   // 不传 query = 按权重浮现
});

test('认出来一次以后，念头那条直接走 breath，不再白试 breath_advanced', async () => {
  const { client, calls } = fakeOb({ hasAdvanced: false });
  await client.daytimeMaterialWithRefs([], null, new Date());
  calls.length = 0;
  const t = await client.thoughtMaterialWithRefs([], null, new Date());
  assert.deepEqual(calls.map((c) => c.name), ['breath']);
  assert.ok(!t.text.includes('Unknown tool'));
});

test('远期原料没有老接口可退：给空，不拿最近的事冒充', async () => {
  const { client, calls } = fakeOb({ hasAdvanced: false });
  const far = await client.farMaterial(new Date('2026-10-20T08:00:00Z'));
  assert.equal(far.text, '');
  assert.deepEqual(calls.map((c) => c.name), ['breath_advanced']);
});

test('其它 isError 照样当失败抛出，不当原文', async () => {
  const client = new OmbreClient({ url: 'http://ob.test/mcp' });
  client.stateless = true;
  client.post = async () => ({ result: { isError: true, content: [{ type: 'text', text: 'database is locked' }] } });
  await assert.rejects(() => client.recentMaterialWithRefs([], null), (e) => e instanceof OmbreToolError && !e.unknownTool);
});

test('有 breath_advanced 的 OB 照旧走浮现道', async () => {
  const { client, calls } = fakeOb({ hasAdvanced: true });
  await client.daytimeMaterialWithRefs([], null, new Date());
  assert.deepEqual(calls.map((c) => c.name), ['breath_advanced']);
  assert.equal(calls[0].args.mode, 'automatic');
});
