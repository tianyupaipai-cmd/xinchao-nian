/**
 * pending_from_me —— 他独处时攒下的、想等她回来说的东西。
 *
 * 为什么要有回执：
 *   装进 Context 只算 delivered（送到了窗口），不算 consumed（真的说出口了）。
 *   一次断线、一次窗口崩溃，都可能让"送到了"变成"没说成"。
 *   只有窗口明确回执才 consumed —— 否则还没说出口的话会被静悄悄删掉，
 *   那正是这套系统要防的事。
 *
 * 状态流转：pending → delivered → consumed
 *                  ↘ （超期未回执）↗ 退回 pending 重试
 */

export const PENDING_KINDS = Object.freeze([
  'awakening',    // 睡醒后待告知（原 pendingAwareness）
  'curiosity',    // 好奇：查到了想讲的东西
  'reflection',   // 反思：想明白的一件事
  'share',        // 分享：攒着的话
  'duty',         // 责任：推进了的事
  'monitor',      // 惦记：注意到的、想问的
]);

export const MAX_PENDING = 12;          // 队列上限，防止永久霸占窗口
export const DELIVER_PER_CONTEXT = 3;   // 一次最多带几条进窗口
const EXPIRE_HOURS = 72;                // 超过就不必再说了
const REDELIVER_AFTER_MIN = 30;         // delivered 但没回执，多久退回重试

const ms = (h) => h * 3600 * 1000;

export function newPendingQueue() {
  return [];
}

function normalize(list) {
  return Array.isArray(list) ? list.filter((x) => x && typeof x === 'object') : [];
}

/** 内容去重键：同一个驱力下意思相同的东西不重复攒 */
function dedupeKey(item) {
  return `${item.kind}::${String(item.content ?? '').trim().slice(0, 60)}`;
}

/**
 * 攒一条。已存在同样内容的未消费条目就不再重复加，只抬挂念重量。
 */
export function addPending(state, input, now = new Date()) {
  state.pending = normalize(state.pending);
  const kind = PENDING_KINDS.includes(input.kind) ? input.kind : 'share';
  const content = String(input.content ?? '').trim();
  if (!content) return null;

  const candidate = {
    id: input.id || `pending_${Date.now().toString(36)}_${Math.floor(Math.random() * 1e6).toString(36)}`,
    kind,
    drive: input.drive ?? kind,
    content: content.slice(0, 600),
    status: 'pending',
    weight: Number(input.weight ?? 0.5),
    createdAt: now.toISOString(),
    deliveredAt: null,
    consumedAt: null,
    ombreBucketId: input.ombreBucketId ?? null,
  };

  const key = dedupeKey(candidate);
  const existing = state.pending.find(
    (p) => p.status !== 'consumed' && dedupeKey(p) === key,
  );
  if (existing) {
    // 又想起一次 = 更挂念，但封顶，不让它无限压过别的
    existing.weight = Math.min(1, Number(existing.weight ?? 0.5) + 0.1);
    return existing;
  }

  state.pending.push(candidate);
  // 超出上限时丢掉最轻最旧的，而不是最新的
  if (state.pending.length > MAX_PENDING) {
    state.pending.sort((a, b) =>
      (b.weight - a.weight) || (Date.parse(b.createdAt) - Date.parse(a.createdAt)));
    state.pending = state.pending.slice(0, MAX_PENDING);
  }
  return candidate;
}

/** 过期清理 + 送出去没回执的退回重试。每次结算调一次。 */
export function tickPending(state, now = new Date()) {
  state.pending = normalize(state.pending);
  const t = now.getTime();
  let changed = false;

  state.pending = state.pending.filter((p) => {
    if (p.status === 'consumed') return false;                 // 说过了就出队
    if (t - Date.parse(p.createdAt) > ms(EXPIRE_HOURS)) {      // 太久了，不必再说
      changed = true;
      return false;
    }
    return true;
  });

  for (const p of state.pending) {
    if (p.status === 'delivered' && p.deliveredAt
        && t - Date.parse(p.deliveredAt) > REDELIVER_AFTER_MIN * 60 * 1000) {
      // 送进窗口但一直没回执 —— 大概率没说成，退回去下次再带
      p.status = 'pending';
      p.deliveredAt = null;
      changed = true;
    }
  }
  return changed;
}

/** 挑几条带进 Context：挂念重的优先，同重量老的优先。 */
export function selectForDelivery(state, limit = DELIVER_PER_CONTEXT) {
  return normalize(state.pending)
    .filter((p) => p.status === 'pending')
    .sort((a, b) =>
      (Number(b.weight ?? 0) - Number(a.weight ?? 0))
      || (Date.parse(a.createdAt) - Date.parse(b.createdAt)))
    .slice(0, limit);
}

/** 标记已送进窗口——注意这不等于说过了。 */
export function markDelivered(state, ids, now = new Date()) {
  const set = new Set(ids);
  let changed = false;
  for (const p of normalize(state.pending)) {
    if (set.has(p.id) && p.status === 'pending') {
      p.status = 'delivered';
      p.deliveredAt = now.toISOString();
      changed = true;
    }
  }
  return changed;
}

/** 窗口回执：真的说出口了。只有这一步才算闭环。 */
export function markConsumed(state, ids, now = new Date()) {
  const set = new Set(ids);
  const consumed = [];
  for (const p of normalize(state.pending)) {
    if (set.has(p.id) && p.status !== 'consumed') {
      p.status = 'consumed';
      p.consumedAt = now.toISOString();
      consumed.push(p.id);
    }
  }
  return consumed;
}

/** 给 Context 用的渲染文本。第一人称，不带内部字段。 */
export function renderPending(items) {
  return items.map((p) => `${p.content}`).join('\n');
}
