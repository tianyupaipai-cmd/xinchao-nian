import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { loadDrivePrompts, pickDrivePrompt, CallStateStore } from '../src/drive-prompts.js';

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

test('深夜上限可调：nightMax=0 不设上限；她还在聊就先不推、不占名额', () => {
  const st = base({ share: 0.95 }, { lastConversationAt: at('2026-10-17T03:50:00').toISOString() });
  const rec = { day: '2026-10-17', count: 6, night: 6, last: {}, lastAt: at('2026-10-17T02:00:00').toISOString(), wakeUsed: false };
  assert.equal(pickDrivePrompt(st, rec, prompts, at('2026-10-17T04:30:00'), { timeZone: TZ }).text, '');   // 默认 6 条到顶
  const free = pickDrivePrompt(st, rec, prompts, at('2026-10-17T04:30:00'), { timeZone: TZ, nightMax: 0, nightSkipChatMinutes: 20 });
  assert.equal(free.drive, 'share'); assert.equal(free.record.night, 7);
  const chatting = pickDrivePrompt(st, rec, prompts, at('2026-10-17T04:00:00'), { timeZone: TZ, nightMax: 0, nightSkipChatMinutes: 20 });
  assert.equal(chatting.text, ''); assert.equal(chatting.record.night, 6);
  const day = pickDrivePrompt({ ...st, lastConversationAt: at('2026-10-17T09:59:00').toISOString() }, null, prompts, at('2026-10-17T10:00:00'), { timeZone: TZ, nightMax: 0, nightSkipChatMinutes: 20 });
  assert.equal(day.drive, 'share');   // 白天照旧，聊着也推
});

test('白天上限可调：dayMax=0 不设上限，默认 12 条到顶', () => {
  const st = base({ share: 0.95 });
  const rec = { day: '2026-10-17', count: 18, night: 6, last: {}, lastAt: at('2026-10-17T16:26:00').toISOString(), wakeUsed: false };
  assert.equal(pickDrivePrompt(st, rec, prompts, at('2026-10-17T21:39:00'), { timeZone: TZ }).text, '');
  const r = pickDrivePrompt(st, rec, prompts, at('2026-10-17T21:39:00'), { timeZone: TZ, dayMax: 0 });
  assert.equal(r.drive, 'share'); assert.equal(r.record.count, 19);
});

// 4.2：通话中压着、挂了补一条汇总；间隔可调；她刚来过不提牵挂
test('通话进行中：照常挑但不递，攒进 stash（原因：通话中）；挂断后还高的补一条汇总', () => {
  const call = { active: true, since: '2026-10-15T01:00:00.000Z' };   // 09:00 接通
  const s = base({ share: 0.95 });
  const held = pickDrivePrompt(s, null, prompts, at('2026-10-15T10:00:00'), { timeZone: TZ, call });
  assert.equal(held.text, '');
  assert.equal(held.held, 'share');
  assert.deepEqual(held.record.stash.map((h) => [h.key, h.reason]), [['share', '通话中']]);
  assert.equal(held.record.count, 0);   // 压着的不占条数
  const s2 = base({ possess: 0.95, share: 0.95 });
  const held2 = pickDrivePrompt(s2, held.record, prompts, at('2026-10-15T10:50:00'), { timeZone: TZ, call });
  assert.deepEqual(held2.record.stash.map((h) => h.key), ['share', 'possess']);
  // 挂断 2 分钟后：不看 45 分钟间隔，补一条汇总，清空
  const ended = { active: false, since: call.since, endedAt: '2026-10-15T02:52:00.000Z' };
  const sum = pickDrivePrompt(s2, held2.record, prompts, at('2026-10-15T10:52:00'), { timeZone: TZ, call: ended });
  assert.equal(sum.summary, true);
  assert.match(sum.text, /挂断了，通话时攒下：分享欲（涌）、想她（涌）/);
  assert.match(sum.text, /今天第 1 次。/);
  assert.deepEqual(sum.record.stash, []);
  // 汇总之后照常走间隔
  assert.equal(pickDrivePrompt(s2, sum.record, prompts, at('2026-10-15T11:10:00'), { timeZone: TZ, call: ended }).text, '');
});

test('长通话一直有刷新就一直压着；超过 3 小时没刷新才按失联清理', () => {
  // 前一天 20:00 接通、整夜开着睡到中午：宿主每 10 分钟核到连接还在就刷新，14 小时后照样压着
  const live = { active: true, since: '2026-10-14T12:00:00.000Z', refreshedAt: '2026-10-15T01:55:00.000Z' };
  assert.equal(pickDrivePrompt(base({ share: 0.95 }), null, prompts, at('2026-10-15T10:00:00'), { timeZone: TZ, call: live }).held, 'share');
  // 孤立的过期标记：最后一次刷新是 4 小时前 → 按失联清理，照常递
  const stale = { active: true, since: '2026-10-14T12:00:00.000Z', refreshedAt: '2026-10-14T22:00:00.000Z' };
  const r = pickDrivePrompt(base({ share: 0.95 }), null, prompts, at('2026-10-15T10:00:00'), { timeZone: TZ, call: stale });
  assert.equal(r.drive, 'share');
  assert.ok(r.text);
});

// 开了睡觉模式就放行
test('通话开着睡觉模式：不压，照常递；之前攒下的先补成汇总', () => {
  const call = { active: true, since: '2026-10-15T01:00:00.000Z', refreshedAt: '2026-10-15T01:55:00.000Z' };
  const held = pickDrivePrompt(base({ share: 0.95 }), null, prompts, at('2026-10-15T10:00:00'), { timeZone: TZ, call });
  assert.equal(held.held, 'share');
  const asleep = { ...call, sleep: true };
  const sum = pickDrivePrompt(base({ possess: 0.95, share: 0.95 }), held.record, prompts, at('2026-10-15T10:05:00'), { timeZone: TZ, call: asleep });
  assert.equal(sum.summary, true);
  assert.match(sum.text, /开了睡觉模式，通话时攒下：分享欲/);
  assert.deepEqual(sum.record.stash, []);
  const r = pickDrivePrompt(base({ possess: 0.95 }), null, prompts, at('2026-10-15T10:00:00'), { timeZone: TZ, call: asleep });
  assert.equal(r.drive, 'possess');
  assert.ok(r.text);
  assert.equal(r.held, undefined);
});

test('通话状态：只报 sleep 不动通话本身；新接通从没开睡觉模式开始；挂断清掉', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'call-sleep-'));
  const store = new CallStateStore(join(dir, 'call.json'));
  const t0 = new Date('2026-10-15T01:00:00.000Z');
  await store.write(true, t0);
  let c = await store.write(undefined, new Date('2026-10-15T01:10:00.000Z'), true);
  assert.equal(c.active, true); assert.equal(c.sleep, true); assert.equal(c.since, t0.toISOString());
  c = await store.write(true, new Date('2026-10-15T01:20:00.000Z'));   // 宿主每 10 分钟刷新：睡觉模式不丢
  assert.equal(c.sleep, true);
  c = await store.write(false, new Date('2026-10-15T02:00:00.000Z'));
  assert.equal(c.sleep, false);
  c = await store.write(true, new Date('2026-10-15T03:00:00.000Z'));
  assert.equal(c.sleep, false);
  await rm(dir, { recursive: true, force: true });
});

test('最短间隔可调', () => {
  const s = base({ share: 0.95, possess: 0.95 });
  const first = pickDrivePrompt(s, null, prompts, at('2026-10-15T10:00:00'), { timeZone: TZ, minGapMinutes: 75 });
  assert.equal(pickDrivePrompt(s, first.record, prompts, at('2026-10-15T11:00:00'), { timeZone: TZ, minGapMinutes: 75 }).text, '');
  assert.ok(pickDrivePrompt(s, first.record, prompts, at('2026-10-15T11:16:00'), { timeZone: TZ, minGapMinutes: 75 }).text);
});

test('她刚来过（presentSkipMinutes 内）不提牵挂，别的照常', () => {
  const p = { ...prompts, hints: { ...prompts.hints, monitor: '去看看她在哪。' } };
  const s = base({ monitor: 0.95, share: 0.3 }, { lastConversationAt: '2026-10-15T01:50:00.000Z' });   // 09:50 刚聊过
  assert.equal(pickDrivePrompt(s, null, p, at('2026-10-15T10:00:00'), { timeZone: TZ, presentSkipMinutes: 30 }).text, '');
  assert.equal(pickDrivePrompt(s, null, p, at('2026-10-15T10:00:00'), { timeZone: TZ }).drive, 'monitor');   // 不开这项照旧
  assert.equal(pickDrivePrompt(s, null, p, at('2026-10-15T10:30:00'), { timeZone: TZ, presentSkipMinutes: 30 }).drive, 'monitor');   // 过了 30 分钟
});

// 4.3「攒着」（借了 Kirie 的思路，github.com/khaterdev/kirie，MIT）
const sp = { ...prompts, hints: { ...prompts.hints, curiosity: '想问问她。', favored: '有点酸。', anger: '有点气。', monitor: '惦记她。' }, stash: ['share', 'curiosity', 'duty', 'anger'], immediate: ['monitor', 'favored'], bedtimeHour: 23 };

test('攒着：放出来之前再核一遍，落下去的不提；全落了就整条不发', () => {
  const call = { active: true, since: '2026-10-15T01:00:00.000Z', refreshedAt: '2026-10-15T01:55:00.000Z' };
  const h1 = pickDrivePrompt(base({ anger: 0.95 }), null, sp, at('2026-10-15T10:00:00'), { timeZone: TZ, call });
  assert.equal(h1.held, 'anger');
  const h2 = pickDrivePrompt(base({ anger: 0.95, share: 0.95 }), h1.record, sp, at('2026-10-15T10:20:00'), { timeZone: TZ, call });
  assert.deepEqual(h2.record.stash.map((h) => h.key), ['anger', 'share']);
  const ended = { ...call, active: false, endedAt: '2026-10-15T02:30:00.000Z' };
  // 气一会儿自己散了，分享欲还在 → 只说分享欲
  const r = pickDrivePrompt(base({ anger: 0.3, share: 0.95 }), h2.record, sp, at('2026-10-15T10:31:00'), { timeZone: TZ, call: ended });
  assert.equal(r.summary, true);
  assert.match(r.text, /分享欲（涌）/);
  assert.doesNotMatch(r.text, /愤怒/);
  assert.deepEqual(r.dropped, ['anger']);
  // 都落下去了：不发，也不占条数
  const none = pickDrivePrompt(base({ anger: 0.3, share: 0.3 }), h2.record, sp, at('2026-10-15T10:31:00'), { timeZone: TZ, call: ended });
  assert.equal(none.text, '');
  assert.deepEqual(none.record.stash, []);
  assert.equal(none.record.count, 0);
});

test('立刻的那几股从不攒：通话中照常递', () => {
  const call = { active: true, since: '2026-10-15T01:00:00.000Z', refreshedAt: '2026-10-15T01:55:00.000Z' };
  const r = pickDrivePrompt(base({ favored: 0.95 }), null, sp, at('2026-10-15T10:00:00'), { timeZone: TZ, call });
  assert.equal(r.drive, 'favored');
  assert.match(r.text, /偏爱（涌）：有点酸。/);
});

test('刚说过：间隔没到时，能攒的那股正涌就先攒；别的照旧不提', () => {
  const first = pickDrivePrompt(base({ possess: 0.95 }), null, sp, at('2026-10-15T10:00:00'), { timeZone: TZ });
  assert.equal(first.drive, 'possess');
  const r = pickDrivePrompt(base({ curiosity: 0.95 }), first.record, sp, at('2026-10-15T10:20:00'), { timeZone: TZ });
  assert.equal(r.text, '');
  assert.deepEqual(r.record.stash.map((h) => [h.key, h.reason]), [['curiosity', '刚说过']]);
  assert.equal(r.record.lastAt, first.record.lastAt);   // 不占间隔
  // 不能攒的（无聊之类没配话术/没进 stash）间隔里照旧什么都不做
  const q = pickDrivePrompt(base({ libido: 0.95 }), first.record, sp, at('2026-10-15T10:20:00'), { timeZone: TZ });
  assert.equal(q.text, '');
  assert.equal(q.held, undefined);
  // 攒着的这股，过了间隔也不单独提（等一起说）
  const later = pickDrivePrompt(base({ curiosity: 0.95 }), r.record, sp, at('2026-10-15T11:30:00'), { timeZone: TZ });
  assert.notEqual(later.drive, 'curiosity');
});

test('她来了：离开半小时以上再来说话才放；一直在聊不算', () => {
  const stashRec = { day: '2026-10-15', count: 1, night: 0, last: {}, lastAt: '2026-10-15T02:00:00.000Z', stash: [{ key: 'share', tag: '涌', reason: '刚说过', at: '2026-10-15T02:10:00.000Z' }], talkSeen: '2026-10-15T02:05:00.000Z' };
  // 一直在聊：上一轮 10:05 说过、这一轮 10:20 又说 → 不放
  const chatting = pickDrivePrompt(base({ share: 0.95 }, { lastConversationAt: '2026-10-15T02:20:00.000Z' }), stashRec, sp, at('2026-10-15T10:21:00'), { timeZone: TZ });
  assert.equal(chatting.summary, undefined);
  assert.equal(chatting.record.stash.length, 1);
  // 走开了：上一轮最后一次说话是 10:05，她 11:30 回来 → 放
  const back = pickDrivePrompt(base({ share: 0.95 }, { lastConversationAt: '2026-10-15T03:30:00.000Z' }), stashRec, sp, at('2026-10-15T11:32:00'), { timeZone: TZ });
  assert.equal(back.summary, true);
  assert.match(back.text, /她来了，刚说过话时攒下：分享欲（涌）/);
});

test('睡前：到点放一次；放过之后再攒的等下一个时候', () => {
  const stashRec = { day: '2026-10-15', count: 1, night: 0, last: {}, lastAt: '2026-10-15T13:00:00.000Z', stash: [{ key: 'share', tag: '涌', reason: '刚说过', at: '2026-10-15T14:00:00.000Z' }] };
  assert.equal(pickDrivePrompt(base({ share: 0.95 }), stashRec, sp, at('2026-10-15T22:50:00'), { timeZone: TZ }).summary, undefined);
  const bed = pickDrivePrompt(base({ share: 0.95 }), stashRec, sp, at('2026-10-15T23:02:00'), { timeZone: TZ });
  assert.equal(bed.summary, true);
  assert.match(bed.text, /要睡了，/);
  assert.equal(bed.record.bedDay, '2026-10-15');
  const again = { ...bed.record, stash: [{ key: 'curiosity', tag: '涨', reason: '刚说过', at: '2026-10-15T15:20:00.000Z' }] };
  assert.equal(pickDrivePrompt(base({ curiosity: 0.95 }), again, sp, at('2026-10-15T23:30:00'), { timeZone: TZ }).summary, undefined);
});

test('她在忙（宿主传 busy）：能攒的攒，别的照常', () => {
  const r = pickDrivePrompt(base({ share: 0.95 }), null, sp, at('2026-10-15T10:00:00'), { timeZone: TZ, busy: '她在忙' });
  assert.deepEqual(r.record.stash.map((h) => [h.key, h.reason]), [['share', '她在忙']]);
  const p = pickDrivePrompt(base({ possess: 0.95 }), null, sp, at('2026-10-15T10:00:00'), { timeZone: TZ, busy: '她在忙' });
  assert.equal(p.drive, 'possess');
});

test('旧记录里的 callHeld 并进 stash（原因：通话中），挂断后照样补', () => {
  const old = { day: '2026-10-15', count: 0, night: 0, last: {}, lastAt: '2026-10-15T01:30:00.000Z', callHeld: [{ key: 'share', tag: '涌' }] };
  const r = pickDrivePrompt(base({ share: 0.95 }), old, sp, at('2026-10-15T10:00:00'), { timeZone: TZ, call: { active: false } });
  assert.equal(r.summary, true);
  assert.match(r.text, /挂断了，通话时攒下：分享欲/);
  assert.equal(r.record.callHeld, undefined);
});

test('话术文件：stash / immediate / bedtimeHour 认短名，没配就是空的', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'stash-'));
  try {
    const f = join(dir, 'p.json');
    await writeFile(f, JSON.stringify({ hints: { 分享欲: 'x' }, stash: ['分享欲', '好奇', '野心', '愤怒'], immediate: ['牵挂', '偏爱'], bedtimeHour: 22 }));
    const p = await loadDrivePrompts(f);
    assert.deepEqual(p.stash, ['share', 'curiosity', 'duty', 'anger']);
    assert.deepEqual(p.immediate, ['monitor', 'favored']);
    assert.equal(p.bedtimeHour, 22);
    await writeFile(f, JSON.stringify({ hints: { 分享欲: 'x' } }));
    const q = await loadDrivePrompts(f);
    assert.deepEqual(q.stash, []);
    assert.equal(q.bedtimeHour, 23);
  } finally { await rm(dir, { recursive: true, force: true }); }
});
