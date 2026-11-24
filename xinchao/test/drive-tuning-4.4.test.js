// 4.4 三个开关（工具检查 / 标签带依据 / 按时段封顶 + 升级提醒）和议题 #7 的回归测试。
// 每个开关都测两头：默认关时和 4.3 一样，打开后按说明生效。
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { loadDrivePrompts, pickDrivePrompt } from '../src/drive-prompts.js';
import { buildNowCompact } from '../src/context-envelope.js';
import { axesLine } from '../src/core-axes.js';
import { newState, computeLonging } from '../src/engine.js';

const TZ = 'Asia/Shanghai';
const at = (s) => new Date(`${s}+08:00`);
const prompts = { hints: { possess: '想她了。', share: '有话想说。', curiosity: '想看看世界。' }, held: [], footer: '今天第 {n} 次。' };
const base = (drives, extra = {}) => ({ drives: { possess: 0.3, monitor: 0.3, share: 0.3, curiosity: 0.3, ...drives }, driveTrail: [], satisfactionPlateaus: {}, ...extra });
const SLOTS = [{ start: 510, end: 720, max: 2 }, { start: 720, end: 1080, max: 2 }];
// 一股连续 h 小时高着（driveTrail 每小时一个点）
const heldFor = (key, value, hours, now) => Array.from({ length: hours + 1 }, (_, i) => ({ at: new Date(now.getTime() - (hours - i) * 3_600_000).toISOString(), drives: { [key]: value } }));

// ---------- C：按时段封顶 ----------
test('C 默认不分时段：同一上午第三条照常（间隔够就递）', () => {
  const s = base({ share: 0.95, curiosity: 0.95, possess: 0.95 });
  let rec = null;
  for (const t of ['2026-11-23T08:40:00', '2026-11-23T09:40:00', '2026-11-23T10:40:00']) {
    const r = pickDrivePrompt(s, rec, prompts, at(t), { timeZone: TZ });
    assert.ok(r.text, `${t} 应该递`);
    rec = r.record;
  }
});

test('C 配了时段：上午两条封顶，第三条不递；到下午名额重新算', () => {
  const s = base({ share: 0.95, curiosity: 0.95, possess: 0.95 });
  let rec = null;
  for (const t of ['2026-11-23T08:40:00', '2026-11-23T09:40:00']) {
    const r = pickDrivePrompt(s, rec, prompts, at(t), { timeZone: TZ, slots: SLOTS });
    assert.ok(r.text); rec = r.record;
  }
  const third = pickDrivePrompt(s, rec, prompts, at('2026-11-23T11:00:00'), { timeZone: TZ, slots: SLOTS });
  assert.equal(third.text, '');
  const pm = pickDrivePrompt(s, third.record, prompts, at('2026-11-23T12:30:00'), { timeZone: TZ, slots: SLOTS });
  assert.ok(pm.text);
});

test('C 升级提醒：涌着两小时没下去的那股不占时段名额，同一段高峰只递一次；默认（0）不开', () => {
  const now = at('2026-11-23T11:00:00');
  const s = base({ curiosity: 0.97 }, { driveTrail: heldFor('curiosity', 0.97, 3, now) });
  const full = { day: '2026-11-23', count: 2, night: 0, last: {}, lastAt: null, slot: { key: '2026-11-23|510', n: 2 } };
  assert.equal(pickDrivePrompt(s, full, prompts, now, { timeZone: TZ, slots: SLOTS }).text, '', '默认不开升级提醒：封顶就不递');
  const esc = pickDrivePrompt(s, full, prompts, now, { timeZone: TZ, slots: SLOTS, escalateHours: 2 });
  assert.equal(esc.drive, 'curiosity');
  assert.match(esc.text, /没下去/);
  assert.equal(esc.record.slot.n, 2, '升级提醒不占名额');
  const again = pickDrivePrompt(s, { ...esc.record, lastAt: null, last: {} }, prompts, at('2026-11-23T11:50:00'), { timeZone: TZ, slots: SLOTS, escalateHours: 2 });
  assert.equal(again.text, '', '同一段高峰只递一次');
});

test('C 一天合计上限 totalMax', () => {
  const s = base({ share: 0.95 });
  const rec = { day: '2026-11-23', count: 6, night: 0, last: {}, lastAt: null };
  assert.equal(pickDrivePrompt(s, rec, prompts, at('2026-11-23T15:00:00'), { timeZone: TZ, totalMax: 6 }).text, '');
  assert.ok(pickDrivePrompt(s, rec, prompts, at('2026-11-23T15:00:00'), { timeZone: TZ }).text, '不配就不管');
});

// ---------- A：工具检查（行动池 + needs + 静音） ----------
async function withPrompts(files, fn) {
  const dir = await mkdtemp(join(tmpdir(), 'xc-44-'));
  try {
    await writeFile(join(dir, 'drive-prompts.json'), JSON.stringify({ hints: { share: '有话想说。', curiosity: '想看看世界。' } }));
    for (const [name, body] of Object.entries(files)) await writeFile(join(dir, name), typeof body === 'string' ? body : JSON.stringify(body));
    await fn(join(dir, 'drive-prompts.json'));
  } finally { await rm(dir, { recursive: true, force: true }); }
}
const pool = { pool: { share: { items: [{ text: '可以寄一张明信片', needs: ['postcard.sh'] }, { text: '可以写两句日记' }] }, curiosity: { items: [{ text: '可以去看鸟', needs: ['birds.sh'] }] } } };

test('A 默认关：needs 不在清单、静音关键词都不过滤', async () => {
  await withPrompts({ 'drive-pool.json': pool, 'scripts-manifest.txt': 'diary.sh\n', 'drive-mute.json': { entries: [{ kw: '日记', until: '2999-01-01T00:00:00Z' }] } }, async (file) => {
    const p = await loadDrivePrompts(file);
    assert.equal(p.actions.share.items.length, 2);
    assert.ok(p.actions.curiosity);
    assert.equal(p.blocked.size, 0);
  });
});

test('A 打开：缺工具的选项不出；一股全被滤掉就这股不出；静音关键词不出', async () => {
  await withPrompts({ 'drive-pool.json': pool, 'scripts-manifest.txt': 'diary.sh\n', 'drive-mute.json': { entries: [{ kw: '日记', until: '2999-01-01T00:00:00Z' }, { kw: '过期的', until: '2000-01-01T00:00:00Z' }] } }, async (file) => {
    const p = await loadDrivePrompts(file, { toolCheck: true });
    assert.ok(p.blocked.has('curiosity'), '看鸟缺 birds.sh：好奇这股不出');
    assert.ok(p.blocked.has('share'), '明信片缺工具、日记被静音：分享欲也不出');
    const r = pickDrivePrompt(base({ curiosity: 0.97, share: 0.97 }), null, p, at('2026-11-23T10:00:00'), { timeZone: TZ });
    assert.equal(r.text, '', '不递空的');
  });
});

test('A 打开但没有清单文件：不按 needs 过滤（清单坏了别全哑）', async () => {
  await withPrompts({ 'drive-pool.json': pool }, async (file) => {
    const p = await loadDrivePrompts(file, { toolCheck: true });
    assert.equal(p.actions.share.items.length, 2);
    assert.equal(p.blocked.size, 0);
  });
});

// ---------- B：情绪标签带依据 ----------
function slightedState(why) {
  const st = newState(at('2026-11-23T08:00:00'));
  st.lastSettledAt = at('2026-11-23T08:00:00').toISOString();
  st.lastConversationAt = at('2026-11-23T08:00:00').toISOString();
  st.emotion = { ...(st.emotion ?? {}), lastCause: 'slighted', lastCauseAt: at('2026-11-23T08:00:00').toISOString(), lastCauseWhy: why };
  return st;
}

test('B 默认关：「刚才被冷落」照旧不带原因', () => {
  const r = buildNowCompact(slightedState(null), at('2026-11-23T10:00:00'), { timeZone: TZ });
  assert.match(r.text, /刚才被冷落/);
  assert.doesNotMatch(r.text, /冷落（/);
});

test('B 打开：被冷落带细项和她多久没来；说不出细项就不挂', () => {
  const withWhy = buildNowCompact(slightedState('被晾着'), at('2026-11-23T10:00:00'), { timeZone: TZ, labelBasis: true });
  assert.match(withWhy.text, /刚才被冷落（被晾着，她 2 小时没来）/);
  const noWhy = buildNowCompact(slightedState(null), at('2026-11-23T10:00:00'), { timeZone: TZ, labelBasis: true });
  assert.doesNotMatch(noWhy.text, /冷落/);
});

test('B 底色：默认只说底色；打开后带「自哪天起」和上次原因，一周没动只在每天第一条出', () => {
  const st = newState(at('2026-11-01T08:00:00'));
  st.axes = { ...(st.axes ?? {}), security: 0.2, confidence: 0.2, lineSig: undefined };
  const plain = axesLine(st, at('2026-11-23T10:00:00'));
  assert.ok(plain, "前提：这个基线下要偏离底色");
  assert.doesNotMatch(plain, /起|上次/);
  st.axes.lineSig = plain.replace('底色：', ''); st.axes.lineSince = at('2026-11-02T08:00:00').toISOString();
  st.axes.why = { security: { label: '被冷落', at: at('2026-11-02T08:00:00').toISOString() } };
  const withBasis = axesLine(st, at('2026-11-23T10:00:00'), { basis: true });
  assert.match(withBasis, /11月2日起/);
  assert.equal(axesLine(st, at('2026-11-23T10:00:00'), { basis: true, seenToday: true }), '', '一周没动、今天出过了：不再挂');
});

// ---------- 议题 #7：挂念 ≥0.35 时「此刻」不能被 render_guard 整块丢掉 ----------
test('#7 挂念高时 /v1/now 照常给出，且不带小数', () => {
  const st = newState(at('2026-11-20T08:00:00'));
  st.lastSettledAt = at('2026-11-23T08:00:00').toISOString();
  st.arrivalHistogram = Array.from({ length: 24 }, (_, h) => (h === 9 || h === 10 ? 10 : 0));
  st.lastConversationAt = at('2026-11-22T10:00:00').toISOString();
  const now = at('2026-11-23T10:30:00');
  const longing = computeLonging(st, now, { timeZone: TZ });
  assert.ok(longing >= 0.35, `前提：挂念要 ≥0.35，实际 ${longing}`);
  const r = buildNowCompact(st, now, { timeZone: TZ });
  assert.equal(r.ok, true, `不该被 ${r.reason} 丢掉`);
  assert.match(r.text, /挂念/);
  assert.doesNotMatch(r.text.replace(/\d+ (条|句)/g, ''), /\d\.\d/);
});
