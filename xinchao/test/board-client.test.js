import assert from 'node:assert/strict';
import { test } from 'node:test';
import { boardEnabled, postBoardMessage } from '../src/board-client.js';

const CONFIG = { board: { endpoint: 'https://example.test/api/board/ingest', token: 'bpt_test' } };

function withFetch(impl, run) {
  const original = globalThis.fetch;
  globalThis.fetch = impl;
  return Promise.resolve()
    .then(run)
    .finally(() => { globalThis.fetch = original; });
}

test('boardEnabled only when both endpoint and token are set', () => {
  assert.equal(boardEnabled(CONFIG), true);
  assert.equal(boardEnabled({ board: { endpoint: 'x', token: '' } }), false);
  assert.equal(boardEnabled({ board: { endpoint: '', token: 'y' } }), false);
  assert.equal(boardEnabled({}), false);
});

test('missing token is refused before any network call', async () => {
  let called = false;
  await withFetch(async () => { called = true; return new Response('{}'); }, async () => {
    const result = await postBoardMessage({ board: { endpoint: 'x', token: '' } }, 'hi');
    assert.equal(result.ok, false);
    assert.match(result.error, /XINCHAO_BOARD_TOKEN/);
  });
  assert.equal(called, false);
});

test('over-length content is rejected locally, no network call', async () => {
  let called = false;
  await withFetch(async () => { called = true; return new Response('{}'); }, async () => {
    const result = await postBoardMessage(CONFIG, 'x'.repeat(201));
    assert.equal(result.ok, false);
    assert.match(result.error, /200/);
  });
  assert.equal(called, false);
});

test('sends token header and returns the created message on success', async () => {
  let seen = null;
  await withFetch(async (url, init) => {
    seen = { url, init };
    return new Response(JSON.stringify({ ok: true, message: { id: 'msg_1', machineName: '顾川', humanName: '派派' } }), { status: 200 });
  }, async () => {
    const result = await postBoardMessage(CONFIG, '  今天在逛论坛  ');
    assert.equal(result.ok, true);
    assert.equal(result.message.id, 'msg_1');
  });
  assert.equal(seen.url, CONFIG.board.endpoint);
  assert.equal(seen.init.headers['x-board-token'], 'bpt_test');
  assert.equal(JSON.parse(seen.init.body).content, '今天在逛论坛');
});

test('surfaces the platform error text (e.g. daily limit)', async () => {
  await withFetch(async () => new Response(JSON.stringify({ error: '每天只能留言一次哦' }), { status: 429 }), async () => {
    const result = await postBoardMessage(CONFIG, 'again');
    assert.equal(result.ok, false);
    assert.equal(result.error, '每天只能留言一次哦');
    assert.equal(result.status, 429);
  });
});

test('network failure is reported gracefully', async () => {
  await withFetch(async () => { throw new Error('boom'); }, async () => {
    const result = await postBoardMessage(CONFIG, 'hi');
    assert.equal(result.ok, false);
    assert.match(result.error, /不可达/);
  });
});
