import test from 'node:test';
import assert from 'node:assert/strict';
import { handleMcpMessage } from '../src/mcp-protocol.js';
import { SYSTEM_VERSION } from '../src/version.js';

const request = (method, params = {}) => ({ jsonrpc: '2.0', id: 1, method, params });

test('MCP handshake reports the shared runtime version', async () => {
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
  assert.ok(names.includes('xinchao_box'));
  assert.equal(names.includes('xinchao_pending_create'), false);
  assert.equal(names.includes('xinchao_pending_consumed'), false);
  assert.ok(names.includes('xinchao_personality_reflect'));
  assert.equal(names.includes('xinchao_pending_hold'), false);
  assert.equal(names.includes('xinchao_pending_drop'), false);
  assert.ok(names.includes('board_post'));
  assert.ok(names.includes('board_read'));
  assert.ok(names.includes('breath'));
  assert.equal(names.includes('purge'), false);
});

test('AI can submit one complete monthly personality reflection through MCP', async () => {
  let received;
  const dimensions = [
    'joy', 'sorrow', 'anger', 'fear', 'disgust', 'surprise', 'love',
    'shame', 'trust', 'desire', 'calm', 'cognition', 'conflict', 'expression',
  ].map((key) => ({ key, score: 70, reason: `AI 回顾 ${key}` }));
  const result = await handleMcpMessage(request('tools/call', {
    name: 'xinchao_personality_reflect',
    arguments: { month: '2026-08', dimensions },
  }), {
    personalityReflect: async (input) => {
      received = input;
      return { month: input.month, duplicate: false };
    },
  });
  assert.equal(result.body.result.isError, false);
  assert.equal(received.month, '2026-08');
  assert.equal(received.dimensions.length, 14);
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

test('hidden tools disappear from tools/list', async () => {
  const result = await handleMcpMessage(request('tools/list'), { toolsHide: new Set(['xinchao_pending_create']) });
  const names = result.body.result.tools.map((tool) => tool.name);
  assert.ok(names.includes('xinchao_box'));
  assert.ok(!names.includes('xinchao_pending_create'));
});

test('xinchao_* tool replies carry a trailing now-line; xinchao_context does not', async () => {
  const handlers = {
    nowLine: async () => '此刻：想她（涌）；情绪 安心',
    handoffNote: async () => ({ revision: 3, duplicate: false }),
    context: async () => ({ delivered: true, additionalContext: 'ctx', sections: [] }),
  };
  const note = await handleMcpMessage(request('tools/call', { name: 'xinchao_handoff_note', arguments: { event_id: 'evt-000001', note: 'x', session_id: 's' } }), handlers);
  assert.match(note.body.result.content[0].text, /此刻：想她（涌）/);
  const ctx = await handleMcpMessage(request('tools/call', { name: 'xinchao_context', arguments: { session_id: 's' } }), handlers);
  assert.doesNotMatch(ctx.body.result.content[0].text, /此刻：/);
});
