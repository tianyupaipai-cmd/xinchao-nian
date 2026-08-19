/**
 * pending_from_me —— 他独处时攒下的、想等她回来说的东西。
 *
 * 为什么要有回执：
 *   装进 Context 只算 delivered（送到了窗口），不算 consumed（真的说出口了）。
 *   一次断线、一次窗口崩溃，都可能让"送到了"变成"没说成"。
 *   只有窗口明确回执才 consumed —— 否则还没说出口的话会被静悄悄删掉，
 *   那正是这套系统要防的事。
 *
 * 两条正交轴：
 *   status（AI 推进）：pending → delivered → consumed
 *                           ↘ （超期未回执）↗ 退回 pending 重试
 *   disposition（只有用户能决定）：null | held | dropped
 *
 * 说没说出口和值不值得留是两件事，不能压成一条状态机。
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
export const CONSUMED_GRACE_HOURS = 24; // 说完后留给用户 hold/drop 的时间
const TERMINAL_AUDIT_HOURS = 24;         // 终态在 state 里短留，便于 UI 确认结果

const ms = (h) => h * 3600 * 1000;

export function newPendingQueue() {
  return [];
}

function normalize(list) {
  if (!Array.isArray(list)) return [];
  const items = list.filter((x) => x && typeof x === 'object');
  for (const item of items) {
    item.disposition = item.disposition === 'held' || item.disposition === 'dropped'
      ? item.disposition
      : null;
    item.dispositionAt ??= null;
    item.holdSync = item.holdSync && typeof item.holdSync === 'object'
      ? item.holdSync
      : null;
    if (item.holdSync) {
      item.holdSync.landedBucketId ??= item.ombreBucketId ?? null;
      item.holdSync.linkedSourceBucketIds = Array.isArray(item.holdSync.linkedSourceBucketIds)
        ? [...new Set(item.holdSync.linkedSourceBucketIds.map(String).filter(Boolean))]
        : [];
    }
  }
  return items;
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
    disposition: null,
    dispositionAt: null,
    holdSync: null,
    ombreBucketId: input.ombreBucketId ?? null,
    sourceOmbreBucketIds: Array.isArray(input.sourceOmbreBucketIds)
      ? [...new Set(input.sourceOmbreBucketIds.map(String).map((id) => id.trim()).filter(Boolean))].slice(0, 8)
      : [],
  };

  const key = dedupeKey(candidate);
  const existing = state.pending.find((p) => p.disposition !== 'dropped' && dedupeKey(p) === key);
  if (existing) {
    // 又想起一次 = 更挂念，但封顶，不让它无限压过别的
    existing.weight = Math.min(1, Number(existing.weight ?? 0.5) + 0.1);
    return existing;
  }

  state.pending.push(candidate);
  // 只限制仍可交付的活动条目。held 和宽限期终态不能因排队被静默删除。
  const active = state.pending
    .filter((p) => p.disposition !== 'dropped' && p.status !== 'consumed')
    .sort((a, b) => (b.weight - a.weight) || (Date.parse(b.createdAt) - Date.parse(a.createdAt)));
  if (active.length > MAX_PENDING) {
    const keep = new Set(active.slice(0, MAX_PENDING).map((p) => p.id));
    state.pending = state.pending.filter(
      (p) => p.disposition === 'held' || p.status === 'consumed' || keep.has(p.id),
    );
  }
  return candidate;
}

/** 过期清理 + 送出去没回执的退回重试。每次结算调一次。 */
export function tickPending(state, now = new Date()) {
  state.pending = normalize(state.pending);
  const t = now.getTime();
  let changed = false;

  state.pending = state.pending.filter((p) => {
    const dispositionAt = Date.parse(p.dispositionAt ?? '');
    if (p.disposition === 'dropped') {
      // dropped 立即退出交付；短留一天仅为让 UI 能显示“已放下”。
      if (Number.isFinite(dispositionAt) && t - dispositionAt > ms(TERMINAL_AUDIT_HOURS)) {
        changed = true;
        return false;
      }
      return true;
    }
    if (p.status === 'consumed' && p.disposition == null) {
      const consumedAt = Date.parse(p.consumedAt ?? '');
      if (Number.isFinite(consumedAt) && t - consumedAt > ms(CONSUMED_GRACE_HOURS)) {
        changed = true;
        return false;
      }
      return true;
    }
    if (p.status === 'consumed' && p.disposition === 'held' && p.holdSync?.status === 'synced') {
      const syncedAt = Date.parse(p.holdSync.syncedAt ?? p.dispositionAt ?? '');
      if (Number.isFinite(syncedAt) && t - syncedAt > ms(TERMINAL_AUDIT_HOURS)) {
        changed = true;
        return false;
      }
      return true;
    }
    if (p.disposition !== 'held' && t - Date.parse(p.createdAt) > ms(EXPIRE_HOURS)) {
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
    .filter((p) => p.status === 'pending' && p.disposition !== 'dropped')
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

/** 用户决定留下：不改 status，只开启 OB 持久化任务。 */
export function holdPending(state, ids, now = new Date()) {
  const set = new Set(ids);
  const held = [];
  for (const p of normalize(state.pending)) {
    if (!set.has(p.id) || p.disposition === 'dropped') continue;
    p.disposition = 'held';
    p.dispositionAt = now.toISOString();
    if (p.holdSync?.status !== 'synced') {
      p.holdSync = {
        status: 'pending',
        attempts: Number(p.holdSync?.attempts ?? 0),
        lastAttemptAt: p.holdSync?.lastAttemptAt ?? null,
        lastError: p.holdSync?.lastError ?? null,
        syncedAt: null,
        landedBucketId: p.ombreBucketId ?? p.holdSync?.landedBucketId ?? null,
        linkedSourceBucketIds: p.holdSync?.linkedSourceBucketIds ?? [],
      };
    }
    held.push(p.id);
  }
  return held;
}

/** 用户决定放下：不改 status，但立即不再交付、不再写 OB。 */
export function dropPending(state, ids, now = new Date()) {
  const set = new Set(ids);
  const dropped = [];
  for (const p of normalize(state.pending)) {
    if (!set.has(p.id)) continue;
    p.disposition = 'dropped';
    p.dispositionAt = now.toISOString();
    p.holdSync = null;
    dropped.push(p.id);
  }
  return dropped;
}

/** 待写 OB 的 held 条目；写失败不会改去留决定，下次继续重试。 */
export function selectForHoldSync(state, limit = 3) {
  return normalize(state.pending)
    .filter((p) => p.disposition === 'held' && p.holdSync?.status !== 'synced')
    .sort((a, b) => Date.parse(a.dispositionAt ?? a.createdAt) - Date.parse(b.dispositionAt ?? b.createdAt))
    .slice(0, Math.max(1, Number(limit) || 1));
}

export function markHoldSyncResult(state, id, result = {}, now = new Date()) {
  const item = normalize(state.pending).find((p) => p.id === id && p.disposition === 'held');
  if (!item) return null;
  const attempts = Number(item.holdSync?.attempts ?? 0) + 1;
  const bucketId = String(result.ombreBucketId ?? item.holdSync?.landedBucketId ?? item.ombreBucketId ?? '').trim();
  const linkedSourceBucketIds = [...new Set([
    ...(item.holdSync?.linkedSourceBucketIds ?? []),
    ...(Array.isArray(result.linkedSourceBucketIds) ? result.linkedSourceBucketIds : []),
  ].map(String).filter(Boolean))];
  if (bucketId) item.ombreBucketId = bucketId;
  if (result.ok && bucketId) {
    item.holdSync = {
      status: 'synced',
      attempts,
      lastAttemptAt: now.toISOString(),
      lastError: null,
      syncedAt: now.toISOString(),
      landedBucketId: bucketId,
      linkedSourceBucketIds,
    };
  } else {
    item.holdSync = {
      status: 'retry',
      attempts,
      lastAttemptAt: now.toISOString(),
      lastError: String(result.error ?? 'ombre_write_failed').slice(0, 240),
      syncedAt: null,
      landedBucketId: bucketId || null,
      linkedSourceBucketIds,
    };
  }
  return item;
}

/** 给 Context 用的渲染文本。第一人称，不带内部字段。 */
export function renderPending(items) {
  return items.map((p) => `${p.content}`).join('\n');
}
