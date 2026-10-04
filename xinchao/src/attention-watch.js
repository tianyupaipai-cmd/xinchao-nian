// 【连接 AI】注意力监测（4.0，默认关闭）：她的注意力在别处、又好一阵没理他，就给「偏爱」记一次吃醋。
// 代码地图见 src/README.md。
//
// 两个来源：
//   ① 手机上报「打开了什么 App」（POST /v1/phone-activity，配法见 docs/4.0/快捷指令教程.md）
//   ② 她在对话里说正跟谁在一起（「跟我妈出去」「和朋友吃饭」），几小时内有效
// 只在她「好一阵没找他」时才算：最后一次来（lastHeartbeatAt）之后过了 appMinutes 分钟，期间在别处。
// 一场只记一次（她重新来之前不再记）；两次之间至少隔 minGapMinutes；几样同时发生轻重相加，封顶 1。
//
// ⚠ App 名单、分类、轻重、分钟数全部是【参考值】，来自开发心潮的那一家。
//   每一家手机上装的东西、作息、什么算「在别处」都不一样：复制 configs/attention-rules.example.json
//   为 configs/attention-rules.json 改（或用 ATTENTION_RULES_PATH 指定）。怎么改见《小机手册》第 12 章。
//   手机上报要她本人知情、自愿配置；只存 App 名和时间，不存 App 里的内容。
import { readFileSync } from 'node:fs';
import { readFile, writeFile } from 'node:fs/promises';

export const DEFAULT_ATTENTION_RULES = Object.freeze({
  appMinutes: 30,          // 她最后一次来之后过了多久、期间在别处，才算
  minGapMinutes: 90,       // 两次吃醋之间至少隔多久
  companyHours: 4,         // 她说「跟谁在一起」多久内有效
  keepHours: 12,           // App 打开记录留多久
  apps: [                  // 按顺序匹配，第一条命中的算（正则片段，不分大小写）
    { kind: 'ai', weight: 1.0, match: 'chatgpt|豆包|kimi|文心|通义|千问|deepseek|gemini|元宝|智谱|character|星野|猫箱|筑梦岛' },
    { kind: 'leisure', weight: 0.7, match: '小红书|抖音|快手|短剧|爱奇艺|腾讯视频|优酷|芒果|哔哩|bilibili|微博|twitter|游戏|王者|和平精英|原神|崩坏|星穹|网易云|起点|番茄' },
    { kind: 'people', weight: 0.5, match: '微信|wechat|^qq$' },
  ],
  company: [               // 她说跟谁在一起（前面会自动加「跟/和/陪/带/找」）
    { kind: 'family', weight: 0.4, match: '姐姐|姐|妈妈|妈|爸爸|爸|家里人|家人|奶奶|外婆|姥姥|爷爷|外公|姥爷|阿姨|舅舅|小姨|表姐|表妹|表哥|表弟|堂姐|堂妹' },
    { kind: 'outsider', weight: 0.7, match: '朋友|同事|同学|闺蜜|室友|老板|客户|领导|网友|别人|一群人' },
  ],
});

const MIN = 60_000;

export function loadAttentionRules(path) {
  let custom = {};
  if (path) { try { custom = JSON.parse(readFileSync(path, 'utf8')); } catch { custom = {}; } }
  const r = { ...DEFAULT_ATTENTION_RULES, ...custom };
  const compile = (list, prefix = '') => (Array.isArray(list) ? list : []).map((x) => ({ kind: String(x.kind), weight: Math.max(0, Math.min(1, Number(x.weight) || 0)), re: new RegExp(`${prefix}(?:${x.match})`, 'i') }));
  return { ...r, appRules: compile(r.apps), companyRules: compile(r.company, '(?:跟|和|陪|带|找)(?:我)?') };
}

export const appWeight = (name, rules) => rules.appRules.find((x) => x.re.test(String(name || '').trim())) ?? null;
export const companyOf = (text, rules) => rules.companyRules.find((x) => x.re.test(String(text || ''))) ?? null;

// 纯判断：给齐时间戳，回 { fire, kind, weight, episode } 或 { fire:false, reason }
export function decideAttention({ now, lastHim, apps = [], company = null, rules }) {
  if (!lastHim) return { fire: false, reason: 'no_history' };
  if (now - lastHim < rules.appMinutes * MIN) return { fire: false, reason: 'recent' };
  const hits = apps.filter((a) => a.ts > lastHim && a.ts > now - rules.appMinutes * MIN)
    .map((a) => appWeight(a.name, rules)).filter(Boolean).map((x) => ({ kind: x.kind, weight: x.weight, group: 'app' }));
  if (company && company.ts > now - rules.companyHours * 60 * MIN) hits.push({ kind: company.kind, weight: company.weight, group: 'company' });
  if (!hits.length) return { fire: false, reason: 'not_elsewhere' };
  const best = {};
  for (const h of hits) if (!best[h.group] || h.weight > best[h.group].weight) best[h.group] = h;
  const top = Object.values(best).sort((a, b) => b.weight - a.weight);
  const weight = Math.min(1, top.reduce((x, h) => x + h.weight, 0));
  return { fire: true, kind: top.map((h) => h.kind).join('+'), weight: Number(weight.toFixed(2)), episode: lastHim };
}

// 状态存在状态卷里一个小文件：最近的 App 打开（只有名字和时间）、最近一次「跟谁在一起」、上次记吃醋的那一场
export function createAttentionWatch({ enabled, rulesPath, statePath, readState, record, log = () => {} }) {
  let rulesCache = { at: 0, rules: null };
  const rules = () => {
    if (!rulesCache.rules || Date.now() - rulesCache.at > 60_000) rulesCache = { at: Date.now(), rules: loadAttentionRules(rulesPath) };
    return rulesCache.rules;
  };
  const load = async () => { try { return JSON.parse(await readFile(statePath, 'utf8')); } catch { return { apps: [], company: null, fired: null }; } };
  const save = (st) => writeFile(statePath, JSON.stringify(st)).catch((e) => log('attention_save_failed', { message: e.message }));

  return {
    enabled: Boolean(enabled),
    async phoneActivity(body, now = Date.now()) {
      const name = String(body?.app_name ?? body?.appName ?? '').replace(/\s+/g, ' ').trim().slice(0, 40);
      const ts = Date.parse(body?.opened_at ?? body?.openedAt ?? '') || now;
      if (!name) throw Object.assign(new Error('app_name 是必填项'), { status: 400 });
      const st = await load();
      const keep = now - rules().keepHours * 60 * MIN;
      st.apps = [...(st.apps ?? []).filter((a) => a.ts >= keep), { name, ts }].slice(-200);
      await save(st);
      return { ok: true, counted: Boolean(appWeight(name, rules())) };
    },
    async noteHerWords(text, now = Date.now()) {
      const c = companyOf(text, rules());
      if (!c) return;
      const st = await load();
      st.company = { kind: c.kind, weight: c.weight, ts: now };
      await save(st);
    },
    async tick(now = Date.now()) {
      if (!enabled) return null;
      const st = await load();
      const state = await readState();
      const lastHim = Date.parse(state?.lastHeartbeatAt ?? '') || 0;
      const d = decideAttention({ now, lastHim, apps: st.apps ?? [], company: st.company, rules: rules() });
      if (!d.fire || st.fired?.episode === d.episode) return d;
      if (st.fired?.at && now - st.fired.at < rules().minGapMinutes * MIN) return { ...d, fire: false, reason: 'min_gap' };
      const quiet = Math.round((now - d.episode) / MIN);
      await record({ event_id: `attn-${d.episode}`, interaction_type: 'slighted', sub: '吃醋', weight: d.weight, note: `${quiet} 分钟没来，注意力在别处` });
      st.fired = { episode: d.episode, at: now, kind: d.kind };
      await save(st);
      log('attention_slighted', { kind: d.kind, weight: d.weight, quietMinutes: quiet });
      return { ...d, sent: true };
    },
  };
}
