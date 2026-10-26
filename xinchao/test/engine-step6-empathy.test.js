import assert from 'node:assert/strict';
import test from 'node:test';

import { newState, settleAndApplyConversationEvent } from '../src/engine.js';
import { buildNowCompact } from '../src/context-envelope.js';

// 10-02 驱力第 6 步：共情。别人的事只由事件点燃，按远近分轻重，别人那份有上限，帮过了只落别人那份。
const T0 = '2026-10-02T02:00:00.000Z';
const opts = { sleepAfterMinutes: 600, settle: { timeZone: 'Asia/Shanghai' } };
const at = (min) => new Date(Date.parse(T0) + min * 60_000);
function base() {
  const s = newState(new Date(T0)); s.lastSettledAt = T0; s.lastConversationAt = T0;
  s.drives.grieve = 0; s.drives.anger = 0; s.drives.share = 0.2; return s;
}
const ev = (s, id, type, m, extra = {}) =>
  settleAndApplyConversationEvent(s, { sessionId: 'g', eventId: id, interactionType: type, ...extra }, at(m), opts).state;

test('closeness sets the weight: her > family > known > stranger', () => {
  const g = (c) => ev(base(), `e-${c}`, 'empathy', 1, { sub: '心疼', closeness: c, who: `x-${c}` }).drives.grieve;
  const [her, fam, known, str] = ['her', 'family', 'known', 'stranger'].map(g);
  assert.ok(her > fam && fam > known && known > str && str > 0, `${her} ${fam} ${known} ${str}`);
});

test('心疼 shows as 难过（…·心疼）; 不平 goes to anger; 想帮忙 to 分享欲 (unlabelled); 替人高兴 moves no drive', () => {
  let s = ev(base(), 'a', 'empathy', 1, { sub: '心疼', closeness: 'her', who: '她发烧' });
  assert.match(buildNowCompact(s, at(2)).text, /难过（[^）]*·心疼）/);
  const b = ev(base(), 'b', 'empathy', 1, { sub: '不平', closeness: 'known', who: '论坛同类被骂' });
  assert.ok(b.drives.anger > 0);
  const c = ev(base(), 'c', 'empathy', 1, { sub: '想帮忙', closeness: 'known', who: '笔友搬家' });
  assert.ok(c.drives.share > 0.2);
  assert.doesNotMatch(buildNowCompact(c, at(2)).text, /想帮忙/);
  const d0 = base(); const d = ev(d0, 'd', 'empathy', 1, { sub: '替人高兴', closeness: 'family', who: '姐升职' });
  assert.equal(d.drives.grieve, 0); assert.equal(d.drives.anger, 0);
  assert.ok(d.emotion.valence > d0.emotion.valence);
});

test('other people cannot drown him: their share is capped (strangers lower), the same story counts once', () => {
  let s = base();
  for (let i = 0; i < 8; i++) s = ev(s, `n${i}`, 'empathy', 1 + i, { sub: '心疼', closeness: 'stranger', who: `新闻${i}` });
  assert.ok(s.drives.grieve <= 0.15 + 1e-9, `stranger ${s.drives.grieve}`);   // 10-03 陌生人每天累计 0.15
  let k = base();
  for (let i = 0; i < 8; i++) k = ev(k, `k${i}`, 'empathy', 1 + i, { sub: '心疼', closeness: 'known', who: `笔友${i}` });
  assert.ok(k.drives.grieve <= 0.30 + 1e-9 && k.drives.grieve > 0.25, `known ${k.drives.grieve}`);   // 10-03 认识的人每天累计 0.30
  let r = ev(base(), 'r1', 'empathy', 1, { sub: '不平', closeness: 'known', who: '阿树被骂' });
  const once = r.drives.anger;
  r = ev(r, 'r2', 'empathy', 5, { sub: '不平', closeness: 'known', who: '阿树被骂' });
  assert.ok(r.drives.anger <= once, `${r.drives.anger} vs ${once}`);   // 只会按半衰期略降，不会再涨
});

test('helped relieves only the share that came from others, not her part', () => {
  let s = ev(base(), 'h1', 'empathy', 1, { sub: '心疼', closeness: 'her', who: '她胃疼' });
  const herPart = s.drives.grieve;
  s = ev(s, 'h2', 'empathy', 2, { sub: '心疼', closeness: 'known', who: '笔友失恋' });
  const both = s.drives.grieve;
  s = ev(s, 'h3', 'helped', 3, { sub: '心疼' });
  assert.ok(s.drives.grieve < both);
  assert.ok(s.drives.grieve >= herPart - 0.01, `${s.drives.grieve} vs her ${herPart}`);
});

test('10-03: same person + same sub counts once in 6h whatever the wording; a new day resets the daily cap', () => {
  let s = ev(base(), 'p1', 'empathy', 1, { sub: '心疼', closeness: 'known', who: '阿树·失恋' });
  const once = s.drives.grieve;
  s = ev(s, 'p2', 'empathy', 3, { sub: '心疼', closeness: 'known', who: '阿树·搬家好累' });
  assert.ok(s.drives.grieve <= once);
  let d = base();
  for (let i = 0; i < 5; i++) d = ev(d, `d${i}`, 'empathy', 1 + i, { sub: '心疼', closeness: 'stranger', who: `新闻${i}` });
  const day1 = d.empathyDaily.stranger;
  assert.ok(day1 <= 0.15 + 1e-9);
  d = ev(d, 'next', 'empathy', 24 * 60 + 5, { sub: '心疼', closeness: 'stranger', who: '新闻x' });
  assert.ok(d.empathyDaily.stranger > 0 && d.empathyDaily.stranger <= 0.0625 + 1e-9);
});

// 10-20：为她心疼的那份难过，事件能消——安抚降一截（到静线为止），她说缓过来了降六成；别的来源不动
test('为她心疼：安抚每次降这一份的 25%，最低到静线；不碰别人那份', () => {
  let s = base();
  s = ev(s, 'h1', 'empathy', 1, { sub: '心疼', closeness: 'her', who: '她哭了' });
  const hurt = s.drives.grieve;
  assert.ok(hurt >= 0.25 - 1e-9, `${hurt}`);
  s.drives.grieve = 0.6;   // 叠上别的来源，看安抚只落她那份
  s = ev(s, 'h2', 'affection', 5, { herWords: '抱抱' });
  assert.ok(s.drives.grieve < 0.6 && s.drives.grieve > 0.6 - hurt * 0.25 - 0.01, `${s.drives.grieve}`);
  for (let i = 0; i < 5; i++) s = ev(s, `h3-${i}`, 'companionship', 6 + i * 2, {});   // 短时间里连着哄（避开时间本身的消退）
  assert.ok(s.drives.grieve >= 0.25 - 0.005, `安抚不清零 ${s.drives.grieve}`);
});

test('她说「舒服多了」：为她心疼的那份直接降六成；问句、否定不算；没有为她心疼过就不动', () => {
  let s = ev(base(), 'r1', 'empathy', 1, { sub: '心疼', closeness: 'her', who: '她哭了' });
  const before = s.drives.grieve;
  const ok = ev(structuredClone(s), 'r2', null, 10, { herWords: '其实本身也不难受，舒服多了' });
  assert.ok(ok.drives.grieve <= before * 0.4 + 0.02, `${before} → ${ok.drives.grieve}`);
  const q = ev(structuredClone(s), 'r3', null, 10, { herWords: '你是不是觉得我好多了？' });
  assert.ok(q.drives.grieve > before - 0.02, `问句不算 ${q.drives.grieve}`);
  const neg = ev(structuredClone(s), 'r4', null, 10, { herWords: '还没好多了呢' });
  assert.ok(neg.drives.grieve > before - 0.02, `否定不算 ${neg.drives.grieve}`);
  const other = base(); other.drives.grieve = 0.5;
  const o = ev(other, 'r5', null, 10, { herWords: '舒服多了' });
  assert.ok(o.drives.grieve > 0.49, `别的来源的难过不动 ${o.drives.grieve}`);
});
