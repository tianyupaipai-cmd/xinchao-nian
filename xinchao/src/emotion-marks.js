// 【情绪】情绪浮标：有起因的情绪亮过的时刻，给网页潮汐带画浮标。
// 代码地图见 src/README.md。
//
// 10-03 情绪线浮标：有起因的情绪在什么时候、因为什么亮了一下，记一份在心潮自己这里，
// 网页的潮汐带拿它画浮标（以前这份记录只在客户端，平台网页读不到）。
// note 是对方那句话的摘要（≤40 字），只在仪表盘开了「显示私密文字」时才给网页；否则只给事件类型。
const KEEP_DAYS = 7;
const MAX_MARKS = 240;
// 10-06 同一种心情连着来就并成一个浮标（n 记次数）：离这种心情上一次出现不到 MERGE_HOURS 就并，心情换了也照并（按词算）。
// 计时从最后一次出现往后算，所以一整段同样的心情只留一个浮标。只影响浮标展示，驱力和情绪计算不读它。参考值。
const MERGE_HOURS = 2;
const iso = (d) => d.toISOString();

// 事件 → 浮标词和分量（和情绪线的起因情绪一一对应）
export function markFor(type, { sub, strength, closeness } = {}) {
  if (type === 'affection' || type === 'intimacy') return sub === '害羞' ? ['害羞', 2] : strength === 'heavy' || type === 'intimacy' ? ['心动', 3] : ['心动', 1];
  if (type === 'empathy') return sub === '心疼' ? ['心疼', 2] : sub === '不平' ? ['不平', 2] : sub === '替人高兴' && closeness === 'her' ? ['骄傲', 2] : null;
  if (type === 'loss') return ({ 自责: ['自责', 3], 委屈: ['委屈', 2], 失落: ['失落', 2], 分别: ['舍不得', 2] })[sub] ?? null;
  if (type === 'conflict') return ['生气', 3];
  if (type === 'slighted') return ['吃醋', 2];
  if (type === 'task_progress' || type === 'discovery') return ['得意', 1];
  return null;
}

export function recordMark(state, word, weight, { type = null, note = '' } = {}, now = new Date()) {
  if (!(weight >= 2)) return;   // 10-03：轻的（日常撒娇、顺手做完的事）不直接记，等它真的点亮了再记（见 emotion.js lightEmotion）
  const cutoff = now.getTime() - KEEP_DAYS * 24 * 3_600_000;
  const list = (Array.isArray(state.emotionMarks) ? state.emotionMarks : []).filter((m) => Date.parse(m.lastAt ?? m.at) >= cutoff);
  const clean = note ? String(note).replace(/\s+/g, ' ').trim().slice(0, 40) : '';
  for (let i = list.length - 1; i >= 0; i -= 1) {
    const m = list[i];
    if (m.word !== word) continue;
    if (now.getTime() - Date.parse(m.lastAt ?? m.at) < MERGE_HOURS * 3_600_000) {
      // 并进去：次数加一、时间往后挪、分量取重的、说明换成最新一句（点开浮标看到的是最近那次）
      m.n = (m.n ?? 1) + 1;
      m.lastAt = iso(now);
      m.weight = Math.max(m.weight, weight);
      if (type) m.type = type;
      if (clean) m.note = clean;
      state.emotionMarks = list.slice(-MAX_MARKS);
      return;
    }
    break;
  }
  list.push({ at: iso(now), word, weight, ...(type ? { type } : {}), ...(clean ? { note: clean } : {}) });
  state.emotionMarks = list.slice(-MAX_MARKS);
}

const TYPE_WHY = {
  affection: '她亲近你', intimacy: '亲密', empathy: '为别人的事', loss: '失落的事', conflict: '吵了一架', slighted: '她的注意力在别处',
  task_progress: '做成了一件事', discovery: '弄明白了一件事', state: '心里慢慢积起来的',
};

// 给仪表盘：最近 24 小时
export function recentMarks(state, now = new Date(), { includePrivateText = false } = {}) {
  const since = now.getTime() - 24 * 3_600_000;
  return (Array.isArray(state.emotionMarks) ? state.emotionMarks : [])
    .filter((m) => Date.parse(m.lastAt ?? m.at) >= since)
    .map((m) => ({ at: m.at, word: m.word, weight: m.weight, ...(m.n > 1 ? { n: m.n, lastAt: m.lastAt } : {}),
      why: (includePrivateText && m.note) || TYPE_WHY[m.type] || '' }));
}
