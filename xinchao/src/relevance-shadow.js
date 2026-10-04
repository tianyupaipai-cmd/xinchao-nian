// 【实验 · 陪跑】Jev 相关性陪跑（10-04）：心潮自己捞上来的记忆（近期记忆 / 白天浮现和念头 / 做梦原料），
// 旁边让 Jev 对每条答一句「这条跟此刻有关吗」，只写日志，不改任何结果。
// 只在 .env 配了 JEV_API_KEY 且 JEV_SHADOW_ENABLED=true 时才跑；默认关。日志在状态卷 jev-shadow.jsonl。
// 参照 = 此刻块 + 最近一轮她说的话（只在内存里留最近一句，不进存档）。
import { appendFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';

const ENDPOINT = 'https://api.typesafe.ai/v1/systemone';
const MAX_ITEMS = 8;
const ITEM_CHARS = 400;
const RECENT_TTL_MS = 2 * 3_600_000;

let lastTurn = null;   // { at, text }

export function noteRecentTurn(text, at = Date.now()) {
  const t = String(text ?? '').replace(/\s+/g, ' ').trim();
  if (t) lastTurn = { at, text: t.slice(0, 120) };
}

// 把捞上来的材料拆成一条条：按空行分段，表头（[domain:…] [bucket_id:…]）和正文并在一起
export function splitMemories(material) {
  const out = [];
  let cur = '';
  for (const block of String(material ?? '').split(/\n\s*\n/)) {
    const b = block.trim();
    if (!b) continue;
    const isHeaderOnly = b.split('\n').every((l) => /^\[[^\]]+\](\s*\[[^\]]+\])*\s*$/.test(l.trim()));
    cur = cur ? `${cur}\n${b}` : b;
    if (!isHeaderOnly) { out.push(cur); cur = ''; }
  }
  if (cur) out.push(cur);
  return out.map((raw) => {
    const id = raw.match(/\[bucket_id:([^\]]+)\]/)?.[1] ?? null;
    const body = raw.split('\n').filter((l) => !/^\s*\[[^\]]+\](\s*\[[^\]]+\])*\s*$/.test(l)).join(' ').replace(/\s+/g, ' ').trim();
    return { id, body };
  }).filter((x) => x.body.length >= 6);
}

export function createRelevanceShadow({ apiKey, enabled, statePath, nowText, log = () => {} }) {
  const logPath = join(dirname(statePath), 'jev-shadow.jsonl');
  const on = Boolean(enabled && apiKey);

  async function judge(source, material) {
    if (!on) return;
    const items = splitMemories(material).slice(0, MAX_ITEMS);
    if (!items.length) return;
    let now = '';
    try { now = String(await nowText()).trim(); } catch { now = ''; }
    const recent = lastTurn && Date.now() - lastTurn.at < RECENT_TTL_MS ? lastTurn.text : '';
    const state = [
      `此刻：\n${now || '（读不到此刻）'}`,
      recent ? `最近一轮她说：${recent}` : '最近一轮：（两小时内没有对话）',
      '候选记忆：',
      ...items.map((x, i) => `【${i + 1}】${x.body.slice(0, ITEM_CHARS)}`),
    ].join('\n');
    const questions = Object.fromEntries(items.map((_, i) => [`r${i + 1}`, {
      type: 'noul',
      instructions: `第 ${i + 1} 条候选记忆跟此刻有关：和此刻的心情、正在惦记的事，或者最近一轮在聊的事情有联系`,
    }]));
    const t0 = Date.now();
    let row;
    try {
      const res = await fetch(ENDPOINT, {
        method: 'POST',
        headers: { Authorization: `Bearer ${apiKey}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: 'jev-latest', state, questions }),
        signal: AbortSignal.timeout(15000),
      });
      const j = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(`HTTP ${res.status} ${JSON.stringify(j).slice(0, 120)}`);
      row = {
        at: new Date().toISOString(), source, ms: Date.now() - t0, model: j.model ?? null,
        recent: recent ? recent.slice(0, 40) : null,
        items: items.map((x, i) => ({ id: x.id, p: j.answers?.[`r${i + 1}`]?.noul ?? null, head: x.body.slice(0, 40) })),
        tokens: { in: j.usage?.input_tokens ?? null, out: j.usage?.output_tokens ?? null },
      };
    } catch (error) {
      row = { at: new Date().toISOString(), source, error: String(error.message).slice(0, 160), count: items.length };
    }
    try { await appendFile(logPath, `${JSON.stringify(row)}\n`); } catch (error) { log('jev_shadow_log_failed', { message: error.message }); }
  }

  return {
    enabled: on,
    // 不等结果、不抛错：陪跑出什么事都不能拖慢或打断心潮本身
    judge(source, material) { if (on) judge(source, material).catch(() => {}); },
  };
}
