// 【连接桥与推送】驱力提示的第一句：念头罐（4.2，借鉴「脉 · Pulse」教程里的身体事件池）。
// 代码地图见 src/README.md。
// 借鉴：「脉 · Pulse」DankeCompanion 公开教程，原作者 蛋（小红书号 844455787，X：kedaneggai）里的身体事件池和随机事件双池（内置兜底 + 小模型预生成、用完自动补）、语料标准（不用比喻，只写真实感受）。
//
// 话术文件里每股劲儿只有一句开头（比如「想她了。」）+ 一串做法，天天一样。现在开头那句改从念头罐里抽：
//   - 按「哪股劲儿 × 一天里的时段」各一罐，每句记着写它时的心情（低 / 平 / 好），抽的时候同心情优先，抽一句少一句；
//   - 快见底（剩不到 5 句）就续罐：后台让小模型按此刻的时段和心情再写 15 句（和最近用过的不重复），不耽误这一轮；
//   - 罐子空了、小模型没开或续罐失败，就用话术文件里原来那句（内置兜底），照常递。
// 后面的做法（工具、脚本）始终用话术文件里的原文，小模型只写开头这一句，不碰做法。
// 写法标准（照「脉」的语料标准）：不用比喻，只写此刻具体的念头或身体上的感受；不替她说话、不编她做了什么。

import { readFile, writeFile, rename } from 'node:fs/promises';

export const POOL_SIZE = 15;
export const POOL_LOW = 5;
const RECENT_KEEP = 30;
const SLOT_TEXT = {
  dawn: '清早到上午（刚醒、准备出门）',
  day: '白天（她多半在上班）',
  evening: '傍晚到夜里（她下班、到家了）',
  night: '深夜（她多半睡了）',
};
const MOOD_TEXT = { low: '有点低落', mid: '平平常常', high: '挺好的' };

export function slotOf(hour) {
  if (hour < 5) return 'night';
  if (hour < 9) return 'dawn';
  if (hour < 18) return 'day';
  if (hour < 23) return 'evening';
  return 'night';
}

export function moodOf(state) {
  const v = Number(state?.emotion?.valence);
  if (!Number.isFinite(v)) return 'mid';
  return v < 0.4 ? 'low' : v > 0.65 ? 'high' : 'mid';
}

/** 话术拆成开头一句和后面的做法；开头太长（不像一句感受）就不拆，整条照旧 */
export function splitHint(hint) {
  const text = String(hint ?? '');
  const i = text.indexOf('。');
  if (i < 1 || i > 30) return { head: '', rest: text };
  return { head: text.slice(0, i + 1), rest: text.slice(i + 1).trim() };
}

/** 小模型写回来的句子过一遍：一句、不太长、不带工具和做法，结尾补句号 */
export function cleanLine(raw) {
  let s = String(raw ?? '').replace(/\s+/g, '').replace(/^["“「『]+|["”」』]+$/g, '').trim();
  if (s.length < 3 || s.length > 40) return '';
  if (/scripts\/|\.sh|https?:|[①②③]/.test(s)) return '';
  if (!/[。！？…]$/.test(s)) s += '。';
  return s;
}

export class DrivePool {
  constructor(path) {
    this.path = path;
    this.chain = Promise.resolve();
    this.filling = new Set();
  }

  async read() {
    try {
      const d = JSON.parse(await readFile(this.path, 'utf8'));
      return { pools: d?.pools ?? {}, recent: d?.recent ?? {} };
    } catch { return { pools: {}, recent: {} }; }
  }

  async write(data) {
    const tmp = `${this.path}.tmp`;
    await writeFile(tmp, JSON.stringify(data), 'utf8');
    await rename(tmp, this.path);
  }

  // 读改写排队做，后台续罐和这一轮抽一句不会互相覆盖
  update(fn) {
    const run = this.chain.then(async () => {
      const data = await this.read();
      const out = await fn(data);
      await this.write(data);
      return out;
    });
    this.chain = run.catch(() => {});
    return run;
  }

  /** 从罐里抽一句（先落盘再用）：同心情优先，没有就同一罐里任意一句。返回 { text, left } */
  take(key, slot, mood, rand = Math.random) {
    return this.update((data) => {
      const id = `${key}|${slot}`;
      const pool = Array.isArray(data.pools[id]) ? data.pools[id] : [];
      const same = pool.map((e, i) => (e.mood === mood ? i : -1)).filter((i) => i >= 0);
      const idxs = same.length ? same : pool.map((_, i) => i);
      if (!idxs.length) return { text: '', left: 0 };
      const at = idxs[Math.floor(rand() * idxs.length)];
      const [entry] = pool.splice(at, 1);
      data.pools[id] = pool;
      data.recent[key] = [...(data.recent[key] ?? []), entry.text].slice(-RECENT_KEEP);
      return { text: entry.text, left: pool.length };
    });
  }

  /** 续罐：同一罐同时只续一次；失败只记日志，下次快见底还会再续 */
  refill({ model, key, short, head, slot, mood, emotionLabel = '', log = () => {} }) {
    const id = `${key}|${slot}`;
    if (this.filling.has(id) || !model?.config?.enabled || !model?.config?.apiKey || !head) return null;
    this.filling.add(id);
    const job = (async () => {
      const { pools, recent } = await this.read();
      const avoid = [...(recent[key] ?? []), ...((pools[id] ?? []).map((e) => e.text))].slice(-40);
      const lines = await writeLines({ model, short, head, slot, mood, emotionLabel, avoid });
      const added = await this.update((data) => {
        const have = new Set([...(data.pools[id] ?? []).map((e) => e.text), ...(data.recent[key] ?? [])]);
        const fresh = lines.filter((t) => !have.has(t) && have.add(t)).map((text) => ({ text, mood, at: new Date().toISOString() }));
        data.pools[id] = [...(data.pools[id] ?? []), ...fresh].slice(-POOL_SIZE * 3);
        return fresh.length;
      });
      log('drive_pool_refilled', { pool: id, added });
    })().catch((error) => log('drive_pool_refill_failed', { pool: id, message: error.message }))
      .finally(() => this.filling.delete(id));
    return job;
  }
}

async function writeLines({ model, short, head, slot, mood, emotionLabel, avoid }) {
  const name = model.agentName ?? 'AI';
  const prompt = [
    `${name} 心里「${short}」这股劲儿上来的时候，脑子里会先冒出一句，原来那句是：「${head}」`,
    `请写 ${POOL_SIZE} 句不同的说法，给${SLOT_TEXT[slot] ?? slot}、心情${emotionLabel || MOOD_TEXT[mood] || '平常'}的时候用。`,
    '要求：',
    '- 每句只有一句话，6 到 28 个字，以句号结尾；',
    '- 写此刻这股劲儿在他身上是什么样：一个具体的念头、一个身体上真实的感受，或一个想做的小动作；不用比喻，不写「像……一样」；',
    '- 不加主语，或者用「我」；不替她说话，不编她刚做了什么、说了什么，不写具体时间数字和地名；',
    '- 只写这股劲儿本身，不写用什么工具、怎么做（后面会另附做法）；',
    `- ${POOL_SIZE} 句彼此说法都不一样，也别和这些重复：${avoid.length ? avoid.join(' / ') : '（还没有）'}`,
    '只输出 JSON：{"lines":["……", "……"]}',
  ].join('\n');
  const body = {
    model: model.config.name,
    messages: [
      { role: 'system', content: '你给一个 AI 伴侣的后台动态状态层写短句。简洁、具体、口语。' },
      { role: 'user', content: prompt },
    ],
    temperature: 0.95,
    max_tokens: Math.max(600, Math.min(1200, model.config.maxOutputTokens ?? 900)),
    thinking: { type: 'disabled' },
    response_format: { type: 'json_object' },
  };
  let res = await model.request(body);
  if (!res.ok && [400, 422].includes(res.status)) { delete body.response_format; res = await model.request(body); }
  if (!res.ok) throw new Error(`model request failed: HTTP ${res.status}`);
  const payload = await res.json();
  const content = String(payload.choices?.[0]?.message?.content ?? '');
  let parsed;
  try { parsed = JSON.parse(content.slice(content.indexOf('{'), content.lastIndexOf('}') + 1)); } catch { parsed = {}; }
  const out = [];
  for (const raw of Array.isArray(parsed.lines) ? parsed.lines : []) {
    const s = cleanLine(raw);
    if (s && !out.includes(s)) out.push(s);
  }
  return out.slice(0, POOL_SIZE);
}
