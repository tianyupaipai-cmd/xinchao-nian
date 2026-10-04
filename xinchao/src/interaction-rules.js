// 【连接 AI】互动判断的把关规则（4.0）：模型判出互动类型以后，用这几道结构性的门把明显判错的拦下来。
// 代码地图见 src/README.md。
//
// ⚠ 这里的词表、名单、阈值全部是【参考值】，来自开发心潮的那一家的说话习惯。
//   每一家的人和 AI 说话方式都不一样，照搬可能会让 AI 无端吃醋、或者永远不心疼。
//   要改成你们自己的：复制 configs/interaction-rules.example.json 为 configs/interaction-rules.json 改，
//   或者用 INTERACTION_RULES_PATH 指到别的位置。怎么一步一步改，见《小机手册》第 12 章
//   「把心潮改成你们自己的版本」和 docs/4.0/按自己情况调.md。
import { readFileSync } from 'node:fs';

export const DEFAULT_RULES = Object.freeze({
  // 分量重的话：一句就算「重」心动
  heavy: ['爱你', '喜欢你', '在乎你', '好想你', '想你了', '你还在就好', '离不开你', '只要你', '最爱', '永远', '一直在', '别离开', '别走', '陪着我', '有你真好', '幸好有你', '你是我的'],
  // 让他害羞的话：被说中心思、被夸、被逗（正则片段）
  shy: ['你(?:是不是|肯定|一定)?[^，。！？\\s]{0,4}(?:想我|喜欢我|害羞|脸红|吃醋|心动)', '被我(?:说中|发现|猜中)', '偷偷', '(?:好|真|最)(?:厉害|棒|帅|可爱|乖|聪明|好看|温柔)', '夸夸你', '奖励你'],
  // 她真的难受：心疼她本人时，她的话里要有这些
  distress: ['疼', '痛', '病', '发烧', '感冒', '难受', '难过', '哭', '委屈', '害怕', '好怕', '吓', '累死', '好累', '累坏', '崩溃', '焦虑', '失眠', '不舒服', '晕', '吐', '出事', '受伤', '伤心', '心慌', '撑不住', '绝望'],
  // 编的、演的：不算共情
  fiction: ['电视剧', '剧里', '剧情', '小说', '动漫', '番剧', '电影里', '游戏里', '角色扮演', '扮演', '编的', '假如', '如果有一天', '故事里'],
  // 日常告别：不算失落、不算被晾着
  dailyBye: ['晚安', '睡了', '去睡', '挂了', '先挂', '去洗澡', '洗澡去', '一会儿见', '等会儿聊', '等下聊', '拜拜', '先忙', '下线了'],
  // 要分开较久：这时候的告别才算「分别」
  longAway: ['出差', '出远门', '几天', '一周', '一个月', '好久', '搬', '回老家', '出国', '走了就', '见不到'],
  // 狠话：刚亲近完说这些才算真吵，其余的嫌弃当撒娇
  harsh: ['滚', '烦死', '别烦', '真的生气', '我生气了', '别说话了', '闭嘴', '讨厌死你', '分手', '别碰我'],
  // 质问：问句里带这些仍然算吵
  accuse: ['为什么总', '凭什么', '你怎么又', '你到底', '你就不能', '你是不是故意'],
  // 亲近之后多久内，一句不太紧的嫌弃当撒娇（分钟）
  softAfterCloseMinutes: 15,
  // 共情的远近名单：名字 → her（她本人）/ family（家人）/ known（认识的人）/ stranger（陌生人）。默认空，按模型判
  closeness: {},
});

const LEVELS = ['her', 'family', 'known', 'stranger'];
const SUBS = { conflict: ['生气', '不满', '不甘心'], loss: ['失落', '委屈', '分别', '自责'], affection: ['害羞'], intimacy: ['害羞'], slighted: ['吃醋', '被晾着', '被忘'] };
const EMPATHY_SUBS = ['心疼', '不平', '想帮忙', '替人高兴'];
const words = (list) => new RegExp((list ?? []).map((w) => String(w)).filter(Boolean).join('|') || '(?!)');

export function loadInteractionRules(path) {
  let custom = {};
  if (path) {
    try { custom = JSON.parse(readFileSync(path, 'utf8')); } catch { custom = {}; }
  }
  const r = { ...DEFAULT_RULES, ...custom };
  return {
    raw: r,
    heavy: words(r.heavy), shy: words(r.shy), distress: words(r.distress), fiction: words(r.fiction),
    dailyBye: words(r.dailyBye), longAway: words(r.longAway), harsh: words(r.harsh), accuse: words(r.accuse),
    softAfterCloseMs: Number(r.softAfterCloseMinutes ?? 15) * 60_000,
    closeness: Object.fromEntries(Object.entries(r.closeness ?? {}).filter(([, v]) => LEVELS.includes(v))),
  };
}

const IS_QUESTION = /[?？]\s*$|(吗|么|呢)[~～。!！\s]*$|要不要|能不能|可不可以|会不会|是不是|好不好/;
const FORGOT = /忘/;
const HE_FORGOT = /你[^，。！？\s]{0,4}忘/;
const SHE_FORGOT = /我[^，。！？\s]{0,4}忘/;

// 把一段 exchange 拆成她说的和他回的。推荐格式「她说：…… 他回：……」；没写就当整段都是她说的。
export function splitExchange(exchange) {
  const t = String(exchange ?? '').replace(/\s+/g, ' ').trim();
  const her = t.match(/她说[：:](.+?)(?:\s*他回[：:]|$)/)?.[1]?.trim();
  const his = t.match(/他回[：:](.+)$/)?.[1]?.trim();
  return { her: her ?? t, his: his ?? '' };
}

// 模型判的结果过一遍门。recent：最近判过的 [{ type, at }]；hasGrudge：心潮里还记着一场架没和好
export function guardTag(tag, herWords, { rules, recent = [], hasGrudge = false, now = Date.now() } = {}) {
  if (!tag?.type) return tag;
  const R = rules ?? loadInteractionRules(null);
  const u = String(herWords ?? '').trim();
  const close = recent.some((c) => ['affection', 'intimacy'].includes(c.type) && now - c.at < R.softAfterCloseMs);
  if (tag.type === 'conflict' && close && Number(tag.tension) < 0.6 && !R.harsh.test(u)) return { ...tag, type: 'affection', sub: null, guarded: 'soft_after_close' };
  const q = IS_QUESTION.test(u) && !R.accuse.test(u);
  // 和好：最近真吵过（还记着仇），并且她这句不是问句
  if (tag.type === 'reconciliation' && (q || !hasGrudge)) return { ...tag, type: 'affection', sub: null, guarded: 'reconciliation' };
  // 她说「我忘了」：是她忘了说好的事 → 被忘（偏爱），不是他自责
  if (tag.type === 'loss' && SHE_FORGOT.test(u) && !HE_FORGOT.test(u)) return { ...tag, type: 'slighted', sub: '被忘', guarded: 'she_forgot' };
  if (tag.type === 'loss' && R.dailyBye.test(u) && !R.longAway.test(u)) return { ...tag, type: 'companionship', sub: null, guarded: 'daily_bye' };
  if (tag.type === 'empathy') {
    const why = !EMPATHY_SUBS.includes(tag.sub) ? 'no_sub' : !LEVELS.includes(tag.closeness) ? 'no_closeness'
      : R.fiction.test(`${u} ${tag.who || ''}`) ? 'fiction'
      : tag.closeness === 'her' && tag.sub === '心疼' && (!R.distress.test(u) || /心疼/.test(u)) ? 'her_not_distressed' : '';
    if (why) return { ...tag, type: 'companionship', sub: null, guarded: `empathy_${why}` };
    // 远近：名单里的名字说了算，不在名单里才信模型
    const names = Object.keys(R.closeness).sort((a, b) => b.length - a.length);
    const byWho = names.find((n) => String(tag.who || '').includes(n));
    const byText = tag.closeness !== 'her' && names.find((n) => `${tag.who || ''} ${u}`.includes(n));
    if (byWho || byText) return { ...tag, closeness: R.closeness[byWho || byText] };
    return tag;
  }
  if (tag.type === 'intrigued') return { ...tag, sub: '想了解她' };
  if (tag.type === 'slighted') {
    const why = !SUBS.slighted.includes(tag.sub) ? 'no_sub'
      : R.dailyBye.test(u) ? 'daily_bye' : tag.sub === '被忘' && !FORGOT.test(u) ? 'no_forgot'
      : tag.sub === '被忘' && HE_FORGOT.test(u) ? 'he_forgot'
      : tag.sub === '被晾着' && !recent.length ? 'no_context' : '';
    if (why === 'he_forgot') return { ...tag, type: 'loss', sub: '自责', guarded: 'slighted_he_forgot' };
    if (why) return { ...tag, type: 'companionship', sub: null, guarded: `slighted_${why}` };
    return tag;
  }
  if (tag.type === 'affection' || tag.type === 'intimacy') {
    const core = u.replace(/[\s，。！？!?,.~～…、]/g, '');
    const strength = R.heavy.test(u) || (tag.strength === 'heavy' && core.length >= 5) ? 'heavy' : 'light';
    return { ...tag, strength, sub: tag.sub === '害羞' || R.shy.test(u) ? '害羞' : null };
  }
  const okSub = SUBS[tag.type]?.includes(tag.sub) && (!q || tag.sub === '害羞') && (tag.type !== 'conflict' || Number(tag.tension) >= 0.5)
    && !(tag.sub === '分别' && !R.longAway.test(u));
  return { ...tag, sub: okSub ? tag.sub : null };
}
