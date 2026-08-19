import test from 'node:test';
import assert from 'node:assert/strict';
import { handleMcpMessage } from '../src/mcp-protocol.js';
import { SYSTEM_VERSION } from '../src/version.js';

const request = (method, params = {}) => ({ jsonrpc: '2.0', id: 1, method, params });

test('MCP handshake reports the shared 3.0 runtime version', async () => {
  const result = await handleMcpMessage(request('initialize', {
    protocolVersion: '2025-06-18',
  }), {});
  assert.equal(result.status, 200);
  assert.equal(result.body.result.serverInfo.version, SYSTEM_VERSION);
});

test('tools/list keeps Xinchao, board and curated OB tools together', async () => {
  const result = await handleMcpMessage(request('tools/list'), {
    boardEnabled: true,
    listObTools: async () => [
      { name: 'breath', description: 'memory', inputSchema: { type: 'object' } },
      { name: 'purge', description: 'must stay hidden', inputSchema: { type: 'object' } },
    ],
  });
  const names = result.body.result.tools.map((tool) => tool.name);
  assert.ok(names.includes('xinchao_context'));
  assert.ok(names.includes('xinchao_pending_create'));
  assert.ok(names.includes('xinchao_pending_consumed'));
  assert.equal(names.includes('xinchao_pending_hold'), false);
  assert.equal(names.includes('xinchao_pending_drop'), false);
  assert.ok(names.includes('board_post'));
  assert.ok(names.includes('board_read'));
  assert.ok(names.includes('breath'));
  assert.equal(names.includes('purge'), false);
});

test('AI may create and acknowledge pending output but cannot choose user disposition', async () => {
  let created;
  let consumed;
  const handlers = {
    pendingCreate: async (input) => {
      created = input;
      return { item: { id: 'pending_1', ...input }, duplicate: false, revision: 2 };
    },
    pendingConsumed: async (input) => {
      consumed = input;
      return { consumed: input.ids, revision: 3 };
    },
  };
  const createResult = await handleMcpMessage(request('tools/call', {
    name: 'xinchao_pending_create',
    arguments: { kind: 'share', content: '下午翻到一件想等她回来说的事。', source_ombre_bucket_ids: ['bucket_a'] },
  }), handlers);
  assert.equal(createResult.body.result.isError, false);
  assert.deepEqual(created.sourceOmbreBucketIds, ['bucket_a']);

  const consumedResult = await handleMcpMessage(request('tools/call', {
    name: 'xinchao_pending_consumed', arguments: { ids: ['pending_1'] },
  }), handlers);
  assert.equal(consumedResult.body.result.isError, false);
  assert.deepEqual(consumed.ids, ['pending_1']);
});

test('OB failure does not remove Xinchao or board tools', async () => {
  const result = await handleMcpMessage(request('tools/list'), {
    boardEnabled: true,
    listObTools: async () => { throw new Error('offline'); },
  });
  const names = result.body.result.tools.map((tool) => tool.name);
  assert.ok(names.includes('xinchao_event'));
  assert.ok(names.includes('board_post'));
  assert.ok(names.includes('board_read'));
});
