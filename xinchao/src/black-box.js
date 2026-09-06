// 黑匣子（3.3）—— 只有 AI 自己能看的地方。
//
// 小雨 2026-09-06 提的："给机装小秘密的地方，真正的小秘密、备忘录、纸条、事件，什么都可以。
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

function initial() { return { schemaVersion: 1, items: [], audit: [] }; }

function newId(now) {
  return `box-${now.getTime().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

export class BlackBox {
  constructor(path) {
    this.store = new StateStore(path, initial);
  }

  async init() { await this.store.read(); }

  async put({ text, kind = 'note', expiresHours = null, title = '', surface = false }, now = new Date()) {
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
    };
    await this.store.update((box) => {
      box.items = this._sweep(box.items ?? [], now);
      box.items.push(item);
      if (box.items.length > MAX_ITEMS) box.items = box.items.slice(-MAX_ITEMS);
      this._audit(box, 'put', item.id, now);
      return box;
    });
    return item;
  }

  async list(now = new Date()) {
    let items = [];
    await this.store.update((box) => { box.items = this._sweep(box.items ?? [], now); items = structuredClone(box.items); return box; });
    return items.sort((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt));
  }

  async read(id, now = new Date()) {
    const items = await this.list(now);
    const item = items.find((x) => x.id === String(id ?? '').trim());
    if (item) await this.store.update((box) => { this._audit(box, 'read', item.id, now); return box; });
    return item ?? null;
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
    return items.filter((x) => x.surface).slice(0, limit).map((x) => ({ id: x.id, kind: x.kind, title: x.title || `${x.text.slice(0, 20)}${x.text.length > 20 ? '…' : ''}` }));
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

export function renderBoxList(items) {
  if (!items.length) return '匣子是空的。';
  return items.map((x) => {
    const when = x.createdAt.slice(0, 16).replace('T', ' ');
    const exp = x.expiresAt ? `，${x.expiresAt.slice(0, 10)} 到期` : '';
    const kept = x.kept ? '，已搬进 OB' : '';
    const surf = x.surface ? '，会在信封里提醒' : '';
    return `- [${x.id}] ${x.kind}${x.title ? ` · ${x.title}` : ''}（${when}${exp}${kept}${surf}）\n  ${x.text.length > 160 ? `${x.text.slice(0, 160)}…` : x.text}`;
  }).join('\n');
}
