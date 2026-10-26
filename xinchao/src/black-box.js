// 【引擎 · 自我】黑匣子：只有 AI 自己能看的地方，不进网页、不推给人。
// 代码地图见 src/README.md。
//
// 黑匣子（3.3）—— 只有 AI 自己能看的地方。
//
// 2026-09-06 提的："给机装小秘密的地方，真正的小秘密、备忘录、纸条、事件，什么都可以。
// 代码写死，人类看不到，只有机有权限，除非人类自己去问机。"
//
// 边界（产品层面的看不到，不是密码学的）：
//   - 单独一个文件存（不在 state.json 里），/v1/state、Dashboard 快照、状态备份天然不含它；
//   - 没有任何 HTTP 路由读它；唯一入口是 MCP 工具 xinchao_box，也就是 AI 自己；
//   - 上下文信封和"此刻"块只出现一句"匣子里有 N 条"，正文要 AI 自己 read；
//   - 不进 OB、不进 breath；AI 想让某条变成正式记忆，用 keep 主动搬出去；
//   - 审计只记 时间 + 动作 + id，不记内容。
import { StateStore } from './state-store.js';

export const BOX_KINDS = Object.freeze(['secret', 'memo', 'note', 'event', 'other']);
const MAX_ITEMS = 200;
const MAX_TEXT = 2000;
const MAX_AUDIT = 200;
const iso = (v) => new Date(v).toISOString();
// 10-20：匣子越堆越多。只标出来让他自己定烧不烧，不自动删。
const STALE_DAYS = 30;            // 放了 30 天、30 天里没 read 过
const REMINDED_STALE_DAYS = 3;    // 到点提醒过 3 天还没烧
const DAY = 86_400_000;
const norm = (t) => String(t ?? '').toLowerCase().replace(/[\s\p{P}\p{S}]+/gu, '');
const grams = (t) => { const s = norm(t); const g = new Set(); for (let i = 0; i < s.length - 1; i += 1) g.add(s.slice(i, i + 2)); return g; };
// 像不像：标题一样（非空），或正文字面重合高（二字组 Jaccard ≥ 0.5，或短的那条八成以上都在长的里）
export function boxSimilar(a, b) {
  if (a.title && b.title && norm(a.title) && norm(a.title) === norm(b.title)) return true;
  const ga = grams(a.text); const gb = grams(b.text);
  if (ga.size < 4 || gb.size < 4) return norm(a.text) === norm(b.text) && norm(a.text).length > 0;
  let inter = 0; for (const x of ga) if (gb.has(x)) inter += 1;
  return inter / (ga.size + gb.size - inter) >= 0.5 || inter / Math.min(ga.size, gb.size) >= 0.8;
}
// 该看看的：返回 { why: 'long' | 'reminded', days } 或 null
export function boxStale(item, now = new Date(), lastReadAt = item.lastReadAt) {
  const nowMs = now.getTime();
  if (item.remindedAt && nowMs - Date.parse(item.remindedAt) >= REMINDED_STALE_DAYS * DAY) return { why: 'reminded', days: Math.floor((nowMs - Date.parse(item.remindedAt)) / DAY) };
  if (item.remindAt && !item.remindedAt) return null;   // 还没到点的提醒不算放久了
  const age = nowMs - Date.parse(item.createdAt);
  const idle = nowMs - Math.max(Date.parse(item.createdAt), Date.parse(lastReadAt ?? '') || 0);
  if (age >= STALE_DAYS * DAY && idle >= STALE_DAYS * DAY) return { why: 'long', days: Math.floor(age / DAY) };
  return null;
}

function initial() { return { schemaVersion: 1, items: [], audit: [] }; }

function newId(now) {
  return `box-${now.getTime().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

export class BlackBox {
  constructor(path) {
    this.store = new StateStore(path, initial);
  }

  async init() { await this.store.read(); }

  async put({ text, kind = 'note', expiresHours = null, title = '', surface = false, when = null, remindAt = null }, now = new Date()) {
    const body = String(text ?? '').trim().slice(0, MAX_TEXT);
    if (!body) throw new Error('text 是必填项');
    const item = {
      id: newId(now),
      kind: BOX_KINDS.includes(kind) ? kind : 'other',
      title: String(title ?? '').replace(/\s+/g, ' ').trim().slice(0, 60) || null,
      text: body,
      createdAt: iso(now),
      expiresAt: Number.isFinite(Number(expiresHours)) && Number(expiresHours) > 0 ? iso(new Date(now.getTime() + Number(expiresHours) * 3_600_000)) : null,
      kept: null,
      // surface：他想提醒自己的一条。上下文信封里只露标题，正文还得他自己 read。
      surface: Boolean(surface),
      // when：这条事本身的日期（可选）；remindAt：到点提醒，到时自动 surface 并（若桥开着）递一句到窗口，提醒过一次就不再提
      when: validIso(when),
      remindAt: validIso(remindAt),
      remindedAt: null,
    };
    let similar = [];
    await this.store.update((box) => {
      box.items = this._sweep(box.items ?? [], now);
      similar = box.items.filter((x) => boxSimilar(x, item)).map((x) => ({ id: x.id, title: x.title || `${x.text.slice(0, 20)}${x.text.length > 20 ? '…' : ''}` })).slice(0, 3);
      box.items.push(item);
      if (box.items.length > MAX_ITEMS) box.items = box.items.slice(-MAX_ITEMS);
      this._audit(box, 'put', item.id, now);
      return box;
    });
    return { ...item, similar };   // similar 只回给他看，不存
  }

  async list(now = new Date()) {
    let items = [];
    await this.store.update((box) => { box.items = this._sweep(box.items ?? [], now); items = structuredClone(box.items); return box; });
    return items.sort((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt));
  }

  async read(id, now = new Date()) {
    const items = await this.list(now);
    const item = items.find((x) => x.id === String(id ?? '').trim());
    // 到点提醒读了也一直露头，直到烧掉（或 unpin）——这是有意的，提醒要一直在眼前（她 09-26 定）
    if (item) await this.store.update((box) => {
      const x = box.items.find((y) => y.id === item.id);
      if (x) x.lastReadAt = iso(now);   // 10-20：放久了没动过的才标出来，所以记一下最近一次 read
      this._audit(box, 'read', item.id, now);
      return box;
    });
    return item ?? null;
  }

  // 3.3.10：只清"要提醒自己"的标记，条目留着
  async unpin(id, now = new Date()) {
    let found = false;
    await this.store.update((box) => {
      const item = box.items.find((x) => x.id === String(id ?? '').trim());
      if (item) { found = true; if (item.surface) { item.surface = false; this._audit(box, 'unpin', item.id, now); } }
      return box;
    });
    return found;
  }

  async burn(id, now = new Date()) {
    let removed = null;
    await this.store.update((box) => {
      const before = box.items.length;
      removed = box.items.find((x) => x.id === String(id ?? '').trim()) ?? null;
      box.items = box.items.filter((x) => x.id !== String(id ?? '').trim());
      if (box.items.length !== before) this._audit(box, 'burn', String(id).trim(), now);
      return box;
    });
    return Boolean(removed);
  }

  async markKept(id, bucketId, now = new Date()) {
    await this.store.update((box) => {
      const item = box.items.find((x) => x.id === String(id ?? '').trim());
      if (item) { item.kept = { bucketId: bucketId ?? null, at: iso(now) }; this._audit(box, 'keep', item.id, now); }
      return box;
    });
  }

  // 信封用：要露头的条目，只给 id / kind / 标题（没标题就取正文前 20 字）
  async surfaced(now = new Date(), limit = 3) {
    const items = await this.list(now);
    // 有日期的按日期近的先露头
    return items.filter((x) => x.surface).sort((a, b) => Date.parse(a.when ?? '9999') - Date.parse(b.when ?? '9999')).slice(0, limit)
      .map((x) => ({ id: x.id, kind: x.kind, title: `${x.title || `${x.text.slice(0, 20)}${x.text.length > 20 ? '…' : ''}`}${x.when ? `（${x.when.slice(5, 10).replace('-', '/')}）` : ''}` }));
  }

  // 10-20：该看看烧不烧的。老条目没有 lastReadAt，就从审计里找最近一次 read
  async stale(now = new Date()) {
    const box = await this.store.read();
    const lastRead = {};
    for (const a of box.audit ?? []) if (a.op === 'read') lastRead[a.id] = a.at;
    return this._sweep(box.items ?? [], now)
      .map((x) => ({ x, st: boxStale(x, now, x.lastReadAt ?? lastRead[x.id]) }))
      .filter((r) => r.st)
      .map(({ x, st }) => ({ id: x.id, title: x.title || `${x.text.slice(0, 20)}${x.text.length > 20 ? '…' : ''}`, ...st }));
  }

  async count(now = new Date()) {
    const box = await this.store.read();
    return this._sweep(box.items ?? [], now).length;
  }

  _sweep(items, now) {
    const nowMs = now.getTime();
    return items.filter((x) => !x.expiresAt || Date.parse(x.expiresAt) > nowMs);
  }

  _audit(box, op, id, now) {
    box.audit = [...(box.audit ?? []), { at: iso(now), op, id }].slice(-MAX_AUDIT);
  }
}

// 到点的提醒：把 remindAt 已过、还没提醒过的条目标成 surface，返回这些条目（给自身信号用）。
BlackBox.prototype.dueReminders = async function dueReminders(now = new Date()) {
  let due = [];
  await this.store.update((box) => {
    box.items = this._sweep(box.items ?? [], now);
    due = box.items.filter((x) => x.remindAt && !x.remindedAt && Date.parse(x.remindAt) <= now.getTime());
    for (const x of due) { x.surface = true; x.remindedAt = iso(now); this._audit(box, 'remind', x.id, now); }
    return box;
  });
  return structuredClone(due);
};

function validIso(value) {
  if (!value) return null;
  const ms = Date.parse(String(value));
  return Number.isFinite(ms) ? new Date(ms).toISOString() : null;
}

export function renderBoxList(items, now = new Date(), staleIds = null) {
  if (!items.length) return '匣子是空的。';
  return items.map((x) => {
    const st = staleIds ? staleIds.get(x.id) : boxStale(x, now);
    const old = st ? (st.why === 'reminded' ? `，⏳ 提醒过 ${st.days} 天了还没烧，看看烧不烧` : `，⏳ 放了 ${st.days} 天没动过，看看烧不烧`) : '';
    const created = x.createdAt.slice(0, 16).replace('T', ' ');
    const exp = x.expiresAt ? `，${x.expiresAt.slice(0, 10)} 到期` : '';
    const kept = x.kept ? '，已搬进 OB' : '';
    const surf = x.surface ? '，会在信封里提醒' : '';
    const when = x.when ? `，事在 ${x.when.slice(0, 10)}` : '';
    const remind = x.remindAt ? (x.remindedAt ? `，${x.remindAt.slice(5, 16).replace('T', ' ')} 提醒过` : `，${x.remindAt.slice(5, 16).replace('T', ' ')} 提醒`) : '';
    return `- [${x.id}] ${x.kind}${x.title ? ` · ${x.title}` : ''}（${created}${exp}${kept}${surf}${when}${remind}${old}）\n  ${x.text.length > 160 ? `${x.text.slice(0, 160)}…` : x.text}`;
  }).join('\n');
}
