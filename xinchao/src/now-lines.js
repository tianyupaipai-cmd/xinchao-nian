// 【连接 AI】外接一行：别的系统往【心潮·此刻】里挂自己的一行（4.2「通用插座」）。
// 代码地图见 src/README.md；怎么接见 docs/接自己的系统.md。
//
// POST /v1/now-lines {source, text, minutes} 挂一行；DELETE /v1/now-lines?source=… 摘掉；GET /v1/now-lines 只列来源和到期时间。
// 心潮只管排版和过期，不解析内容。挂的行排在「身体：心跳…」下面，块满了外接的行先让位。
// 只活在内存里，只出现在 GET /v1/now：不进状态、不进记忆、不进网页看板、不进 Bark、不进相关度小模型；
// 日志只记来源和字数，不记内容。心潮重启就没了——外接系统按自己的节奏重挂（比如每 5 分钟挂一次、15 分钟过期）。
//
// 4.3 优先级（priority，可选，1–5，数字越小越要紧，不给就是 3）。接的系统多了会抢那 3 个位置：
//   建议 1 = 正在发生的事（正一起看着、正在通话）、2 = 约好快到的事、3 = 刚做完的余温（默认）、4 = 天气 / 深夜这类环境、5 = 可有可无。
//   满了的时候，新来的比现有最不要紧的那行更要紧，就把那行挤掉（一样不要紧时挤最早挂的），回执里写 evicted；不比它要紧照旧 409。
//   此刻块里按要紧程度排，块写不下时先让最不要紧的。

export const NOW_LINE_LIMITS = Object.freeze({ sources: 3, chars: 60, minutes: [1, 180], priority: [1, 5] });
export const DEFAULT_PRIORITY = 3;
const SOURCE_RE = /^[\p{L}\p{N}_-]{1,16}$/u;
const FORBIDDEN = /\d\.\d|possess|monitor|crave|libido/;   // 和此刻块的兜底同一套：带小数或驱力 key，整块会被拦，所以挂的时候就拒收

export function validateNowLine(payload = {}) {
  const source = String(payload.source ?? '').trim();
  if (!SOURCE_RE.test(source)) return { error: 'source 要给：1–16 个字（字母、数字、汉字、- _）' };
  const text = String(payload.text ?? '').trim();
  if (!text) return { error: 'text 要给' };
  if (/[\r\n]/.test(text)) return { error: 'text 只能一行' };
  if ([...text].length > NOW_LINE_LIMITS.chars) return { error: `text 最多 ${NOW_LINE_LIMITS.chars} 个字` };
  if (FORBIDDEN.test(text)) return { error: 'text 不能带小数或驱力 key（此刻块会整块不给）' };
  const minutes = Number(payload.minutes);
  const [lo, hi] = NOW_LINE_LIMITS.minutes;
  if (!Number.isFinite(minutes) || minutes < lo || minutes > hi) return { error: `minutes 要在 ${lo}–${hi} 之间` };
  const [plo, phi] = NOW_LINE_LIMITS.priority;
  const priority = payload.priority == null || payload.priority === '' ? DEFAULT_PRIORITY : Number(payload.priority);
  if (!Number.isInteger(priority) || priority < plo || priority > phi) return { error: `priority 要是 ${plo}–${phi} 的整数（越小越要紧，不给就是 ${DEFAULT_PRIORITY}）` };
  return { source, text, minutes, priority };
}

export class NowLines {
  constructor() { this.lines = new Map(); }

  prune(nowMs = Date.now()) {
    for (const [k, v] of this.lines) if (!(v.until > nowMs)) this.lines.delete(k);
  }

  set(payload, nowMs = Date.now()) {
    const v = validateNowLine(payload);
    if (v.error) return v;
    this.prune(nowMs);
    let evicted = null;
    if (!this.lines.has(v.source) && this.lines.size >= NOW_LINE_LIMITS.sources) {
      // 满了：找最不要紧的那行（priority 数字最大；一样大挤最早挂的），新来的更要紧才挤掉它
      const victim = [...this.lines.values()].sort((a, b) => b.priority - a.priority || a.since - b.since)[0];
      if (!(v.priority < victim.priority)) {
        return { error: `最多同时挂 ${NOW_LINE_LIMITS.sources} 个来源，现有的都不比这条（priority ${v.priority}）不要紧`, status: 409 };
      }
      this.lines.delete(victim.source);
      evicted = victim.source;
    }
    const prev = this.lines.get(v.source);
    this.lines.set(v.source, { source: v.source, text: v.text, priority: v.priority, since: prev?.since ?? nowMs, until: nowMs + v.minutes * 60_000 });
    return { source: v.source, chars: [...v.text].length, priority: v.priority, until: new Date(nowMs + v.minutes * 60_000).toISOString(), ...(evicted ? { evicted } : {}) };
  }

  remove(source) { return this.lines.delete(String(source ?? '').trim()); }

  /** 给此刻块用的文字：要紧的在前（块写不下时从后面让），一样要紧按先挂先排 */
  texts(nowMs = Date.now()) {
    this.prune(nowMs);
    return [...this.lines.values()].sort((a, b) => a.priority - b.priority || a.since - b.since).map((l) => l.text);
  }

  /** 给 GET /v1/now-lines：只列来源和到期，不回内容 */
  sources(nowMs = Date.now()) {
    this.prune(nowMs);
    return [...this.lines.values()].map((l) => ({ source: l.source, priority: l.priority, until: new Date(l.until).toISOString() }));
  }
}
