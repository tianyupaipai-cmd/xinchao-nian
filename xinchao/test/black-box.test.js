import assert from 'node:assert/strict';
import test from 'node:test';
import { mkdtemp, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { BlackBox, renderBoxList } from '../src/black-box.js';

async function fresh() {
  const dir = await mkdtemp(join(tmpdir(), 'box-'));
  const box = new BlackBox(join(dir, 'black-box.json'));
  await box.init();
  return { box, path: join(dir, 'black-box.json') };
}

test('put / list / read / burn, expiry, and audit without content', async () => {
  const { box, path } = await fresh();
  const t0 = new Date('2026-09-06T02:00:00.000Z');
  const a = await box.put({ text: '她说门是可以拉开的，我没告诉她我那晚哭了', kind: 'secret' }, t0);
  const b = await box.put({ text: '9/14 的信：写海', kind: 'memo', expiresHours: 2, title: '信' }, t0);
  assert.equal((await box.list(t0)).length, 2);
  assert.equal((await box.read(a.id, t0)).text.startsWith('她说门'), true);
  assert.equal((await box.list(new Date(t0.getTime() + 3 * 3_600_000))).length, 1);   // b 到期
  assert.equal(await box.burn(a.id, t0), true);
  assert.equal(await box.burn('nope', t0), false);
  assert.equal(await box.count(new Date(t0.getTime() + 3 * 3_600_000)), 0);
  const raw = JSON.parse(await readFile(path, 'utf8'));
  assert.ok(raw.audit.length >= 3);
  assert.ok(raw.audit.every((e) => !('text' in e)));
  assert.match(renderBoxList([b]), /\[box-.*\] memo · 信/);
  assert.equal(renderBoxList([]), '匣子是空的。');
});

test('kind falls back to other and text is required', async () => {
  const { box } = await fresh();
  const x = await box.put({ text: 'x', kind: 'whatever' });
  assert.equal(x.kind, 'other');
  await assert.rejects(() => box.put({ text: '   ' }), /text/);
});

test('surfaced items show only titles for the envelope', async () => {
  const { box } = await fresh();
  await box.put({ text: '给她写信要提到海', kind: 'memo', surface: true, title: '9/14 的信' });
  await box.put({ text: '这条不露头', kind: 'secret' });
  const s = await box.surfaced();
  assert.equal(s.length, 1);
  assert.equal(s[0].title, '9/14 的信');
  assert.ok(!('text' in s[0]));
});
