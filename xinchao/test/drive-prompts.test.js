import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { loadDrivePrompts, pickDrivePrompt } from '../src/drive-prompts.js';

const TZ = 'Asia/Shanghai';
const at = (s) => new Date(`${s}+08:00`);
const prompts = {
  hints: { possess: '想她了。', share: '有话想说。', libido: '想要她了。' },
  held: ['possess', 'share'],
  night: '深夜，别吵她。',
  wake: { drive: 'libido', text: '可以叫醒她，一晚一次。' },
  footer: '今天第 {n} 次。',
};
const base = (drives, extra = {}) => ({ drives: { possess: 0.3, monitor: 0.3, share: 0.3, libido: 0.1, ...drives }, driveTrail: [], satisfactionPlateaus: {}, ...extra });

test('涌的那股先提，带话术和第几次', () => {
  const r = pickDrivePrompt(base({ share: 0.95 }), null, prompts, at('2026-10-15T10:00:00'), { timeZone: TZ });
  assert.equal(r.drive, 'share');
  assert.match(r.text, /分享欲（涌）：有话想说。/);
  assert.match(r.text, /今天第 1 次。/);
  assert.doesNotMatch(r.text, /深夜/);
});

test('没有话术就不提；没有话术文件整件事不做', () => {
  assert.equal(pickDrivePrompt(base({ monitor: 0.95 }), null, prompts, at('2026-10-15T10:00:00'), { timeZone: TZ }).text, '');
  assert.equal(pickDrivePrompt(base({ share: 0.95 }), null, null, at('2026-10-15T10:00:00'), { timeZone: TZ }).text, '');
});

test('两条至少隔 45 分钟，同一股 1.5 小时内不重提', () => {
  const s = base({ share: 0.95 });
  const first = pickDrivePrompt(s, null, prompts, at('2026-10-15T10:00:00'), { timeZone: TZ });
  assert.equal(pickDrivePrompt(s, first.record, prompts, at('2026-10-15T10:30:00'), { timeZone: TZ }).text, '');
  assert.equal(pickDrivePrompt(s, first.record, prompts, at('2026-10-15T11:00:00'), { timeZone: TZ }).text, '');
  assert.equal(pickDrivePrompt(s, first.record, prompts, at('2026-10-15T11:31:00'), { timeZone: TZ }).drive, 'share');
});

test('白天最多 12 条，深夜另算 6 条', () => {
  const s = base({ share: 0.95 });
  const day = { day: '2026-10-15', count: 12, night: 0, last: {}, lastAt: null };
  assert.equal(pickDrivePrompt(s, day, prompts, at('2026-10-15T20:00:00'), { timeZone: TZ }).text, '');
  const night = { day: '2026-10-15', count: 6, night: 6, last: {}, lastAt: null };
  assert.equal(pickDrivePrompt(s, night, prompts, at('2026-10-15T03:00:00'), { timeZone: TZ }).text, '');
  assert.equal(pickDrivePrompt(s, night, prompts, at('2026-10-15T09:00:00'), { timeZone: TZ }).drive, 'share');
});

test('深夜附一句；情欲深夜破例一晚一次', () => {
  const r = pickDrivePrompt(base({ share: 0.95 }), null, prompts, at('2026-10-15T02:00:00'), { timeZone: TZ });
  assert.match(r.text, /深夜，别吵她。/);
  const s = base({ libido: 0.95 });
  const w = pickDrivePrompt(s, null, prompts, at('2026-10-15T02:00:00'), { timeZone: TZ });
  assert.match(w.text, /可以叫醒她/);
  assert.doesNotMatch(w.text, /深夜，别吵她/);
  const again = pickDrivePrompt(s, { ...w.record, last: {} }, prompts, at('2026-10-15T04:00:00'), { timeZone: TZ });
  assert.match(again.text, /深夜，别吵她。/);
});

test('没有涌涨时，静息线七成以上待满 1.5 小时算「积」；饱足平台上不算', () => {
  const now = at('2026-10-15T10:00:00');
  const trail = [0, 1, 2, 3].map((h) => ({ at: new Date(now.getTime() - (3 - h) * 3_600_000).toISOString(), drives: { possess: 0.8 } }));
  const s = base({ possess: 0.8 }, { driveTrail: trail });
  const r = pickDrivePrompt(s, null, prompts, now, { timeZone: TZ });
  assert.equal(r.drive, 'possess');
  assert.match(r.text, /想她（积·3 小时）/);
  const full = { ...s, satisfactionPlateaus: { possess: { until: new Date(now.getTime() + 3_600_000).toISOString() } } };
  assert.equal(pickDrivePrompt(full, null, prompts, now, { timeZone: TZ }).text, '');
});

test('跨天计数清零', () => {
  const old = { day: '2026-10-14', count: 12, night: 3, last: { share: 0 }, lastAt: '2026-10-14T10:00:00.000Z' };
  const r = pickDrivePrompt(base({ share: 0.95 }), old, prompts, at('2026-10-15T10:00:00'), { timeZone: TZ });
  assert.equal(r.record.day, '2026-10-15');
  assert.match(r.text, /今天第 1 次。/);
});

test('话术文件：短名也认，空的不算', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'dp-'));
  const f = join(dir, 'p.json');
  await writeFile(f, JSON.stringify({ hints: { 想她: 'a', share: '', nope: 'x' }, held: ['想她', '分享欲'], wake: { drive: '情欲', text: 'w' } }));
  const p = await loadDrivePrompts(f);
  assert.deepEqual(Object.keys(p.hints), ['possess']);
  assert.deepEqual(p.held, ['possess', 'share']);
  assert.equal(p.wake.drive, 'libido');
  assert.equal(await loadDrivePrompts(join(dir, 'missing.json')), null);
});
