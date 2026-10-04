import assert from 'node:assert/strict';
import test from 'node:test';
import { mkdtemp } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { CabinStore } from '../src/cabin-store.js';

test('AI 收件箱：开锁来信给正文，自己写过的信也在，上锁信只给数量和时间', async () => {
  const store = new CabinStore(join(await mkdtemp(join(tmpdir(), 'cabin-')), 'cabin.json'));
  await store.init();
  const open = await store.addNote({ from: 'user', content: '开着锁的信', eventId: 'u-open-001', locked: false });
  await store.addNote({ from: 'user', content: '锁着的秘密', eventId: 'u-lock-001' });
  await store.addNote({ from: 'ai', content: '我的回信', eventId: 'a-reply-01' });
  const box = await store.aiInbox();
  assert.deepEqual(box.letters.map((n) => n.id), [open.note.id]);
  assert.equal(box.mine.length, 1);
  assert.equal(box.mine[0].content, '我的回信');
  assert.equal(box.mine[0].readAt, null);
  assert.equal(box.lockedCount, 1);
  assert.ok(box.lockedLatestAt);
  assert.ok(!JSON.stringify(box).includes('锁着的秘密'), '上锁正文绝不出现');
});

test('AI 已读：没读过的来信不管放多久都算未读，读一次才记已读，那次仍标为新信', async () => {
  const store = new CabinStore(join(await mkdtemp(join(tmpdir(), 'cabin-')), 'cabin.json'));
  await store.init();
  await store.addNote({ from: 'user', content: '三天前的信', eventId: 'u-old-0001', locked: false, timestamp: '2026-01-01T00:00:00.000Z' });
  await store.addNote({ from: 'user', content: '锁着的', eventId: 'u-lock-002' });
  const peek = await store.aiInbox({ mineLimit: 0 });
  assert.equal(peek.letters.filter((n) => !n.aiReadAt).length, 1, '只看不读不记已读');
  const first = await store.aiInbox({ markRead: true });
  assert.equal(first.letters[0].aiReadAt, null, '这次读到的还标作新信');
  const after = await store.aiInbox({ mineLimit: 0 });
  assert.ok(after.letters[0].aiReadAt);
  assert.equal(after.lockedCount, 1, '上锁的信不受影响');
  assert.equal((await store.snapshot()).aiUnreadUserNotes, 0);
});
