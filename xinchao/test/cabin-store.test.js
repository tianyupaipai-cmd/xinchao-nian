import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import test from 'node:test';
import { CabinStore } from '../src/cabin-store.js';

test('locked user notes stay out of the AI inbox until the user unlocks them', async (t) => {
  const directory = await mkdtemp(join(tmpdir(), 'xinchao-cabin-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const store = new CabinStore(join(directory, 'cabin.json'));

  const created = await store.addNote({
    eventId: 'note-event-0001',
    from: 'user',
    content: '这是一封只在开锁后才能被看到的信。',
    locked: true,
  });
  assert.equal((await store.unlockedUserNotes()).length, 0);

  await store.setNoteLock(created.note.id, false);
  assert.equal((await store.unlockedUserNotes())[0].content, '这是一封只在开锁后才能被看到的信。');

  const duplicate = await store.addNote({
    eventId: 'note-event-0001',
    from: 'user',
    content: '重试不应覆盖原文',
  });
  assert.equal(duplicate.duplicate, true);
  assert.equal(duplicate.note.content, '这是一封只在开锁后才能被看到的信。');
});

test('AI unread notes and love ledger totals are persisted and editable', async (t) => {
  const directory = await mkdtemp(join(tmpdir(), 'xinchao-cabin-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const store = new CabinStore(join(directory, 'cabin.json'));

  await store.addNote({ eventId: 'ai-note-event-1', from: 'ai', content: '我给你留了一句话。' });
  assert.equal((await store.snapshot()).unreadAiNotes, 1);
  await store.markAiNotesRead();
  assert.equal((await store.snapshot()).unreadAiNotes, 0);

  const expense = await store.addLedger({ eventId: 'ledger-expense-1', type: 'expense', item: '晚餐', amount: 88.88, date: '2026-08-09' });
  await store.addLedger({ eventId: 'ledger-income-1', type: 'income', item: '共同基金', amount: 20, date: '2026-08-09' });
  assert.deepEqual((await store.snapshot()).totals, { expense: 88.88, income: 20, net: 68.88 });

  await store.updateLedger(expense.entry.id, { amount: 66.66 });
  assert.deepEqual((await store.snapshot()).totals, { expense: 66.66, income: 20, net: 46.66 });
  await store.deleteLedger(expense.entry.id);
  assert.deepEqual((await store.snapshot()).totals, { expense: 0, income: 20, net: -20 });
});
