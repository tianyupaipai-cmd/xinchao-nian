// 【连接 AI】订阅推送：别的系统连 GET /v1/stream（SSE），心潮状态一变就推一条，不用轮询（4.2「通用插座」②）。
// 代码地图见 src/README.md；怎么接见 docs/接自己的系统.md。
//
// 只在这些时候推：某股劲儿换档（静 / 平 / 涨 / 涌 / 落）、情绪换了标签、睡着 / 醒了、有劲儿得到满足（/v1/satisfy）。
// 内容只给 key、短名、档位、时间，不给小数；同一股劲儿 1 分钟内最多推一次（挡住来回抖）。
// 为什么是 SSE 不是回调网址：心潮跑在每家自己的机器上，让它往任意网址发请求，等于能被拿来访问内网别的服务；
// SSE 是外部系统来连心潮，用同一个 token，心潮不主动往外发。

import { DIMENSIONS, DRIVE_SHORT, driveLevel } from './dimensions.js';
import { driveTrend } from './engine.js';

export const STREAM_THROTTLE_MS = 60_000;
export const STREAM_MAX_CLIENTS = 10;

function levels(state, now) {
  const out = {};
  for (const key of Object.keys(DIMENSIONS)) {
    out[key] = driveLevel(key, Number(state?.drives?.[key]), driveTrend(state, key, now));
  }
  return out;
}

/** 前后两份状态比一比，出要推的事件。lastSent 记每股劲儿上次推的时刻（就地更新） */
export function diffEvents(before, after, now = new Date(), { meta = {}, lastSent = new Map(), throttleMs = STREAM_THROTTLE_MS } = {}) {
  if (!before || !after) return [];
  const at = now.toISOString();
  const nowMs = now.getTime();
  const events = [];
  const a = levels(before, now);
  const b = levels(after, now);
  for (const key of Object.keys(b)) {
    if (a[key] === b[key]) continue;
    if (nowMs - Number(lastSent.get(key) ?? 0) < throttleMs) continue;
    lastSent.set(key, nowMs);
    events.push({ type: 'drive', key, name: DRIVE_SHORT[key] ?? key, level: b[key], prev: a[key], at });
  }
  const la = before?.emotion?.label;
  const lb = after?.emotion?.label;
  if (lb && la !== lb) events.push({ type: 'emotion', label: lb, prev: la ?? null, at });
  if ((before?.consciousness === 'sleeping') !== (after?.consciousness === 'sleeping')) {
    events.push({ type: 'sleep', asleep: after?.consciousness === 'sleeping', at });
  }
  if (meta.type === 'satisfy' && Array.isArray(meta.details?.drives) && meta.details.drives.length) {
    events.push({ type: 'satisfy', drives: meta.details.drives.map((k) => ({ key: k, name: DRIVE_SHORT[k] ?? k })), at });
  }
  return events;
}
