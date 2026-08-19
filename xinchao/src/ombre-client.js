import { SYSTEM_VERSION } from './version.js';

export class OmbreClient {
  constructor(config) {
    this.config = config;
    this.sessionId = null;
    this.initializePromise = null;
  }

  async post(payload, expectBody = true) {
    const headers = {
      'Content-Type': 'application/json',
      Accept: 'application/json, text/event-stream',
      'X-Ombre-Caller': 'dynamic-mind',
    };
    if (this.config.token) headers.Authorization = `Bearer ${this.config.token}`;
    if (this.sessionId) headers['Mcp-Session-Id'] = this.sessionId;
    const response = await fetch(this.config.url, {
      method: 'POST', headers,
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(15000)
    });
    if (!response.ok) throw new Error(`Ombre MCP failed: HTTP ${response.status}`);
    this.sessionId = response.headers.get('mcp-session-id') ?? this.sessionId;
    if (!expectBody) return null;
    const text = await response.text();
    return text ? parseMcp(text) : null;
  }

  async initialize() {
    if (this.sessionId) return;
    if (!this.initializePromise) {
      this.initializePromise = (async () => {
        await this.post({
          jsonrpc: '2.0',
          id: Date.now(),
          method: 'initialize',
          params: {
            protocolVersion: '2025-06-18',
            capabilities: {},
            clientInfo: { name: 'xinchao-dynamic-mind', version: SYSTEM_VERSION },
          },
        });
        if (!this.sessionId) throw new Error('Ombre MCP did not return a session id');
        await this.post({ jsonrpc: '2.0', method: 'notifications/initialized' }, false);
      })().finally(() => { this.initializePromise = null; });
    }
    return this.initializePromise;
  }

  async call(name, args = {}) {
    for (let attempt = 0; attempt < 2; attempt += 1) {
      await this.initialize();
      try {
        return await this.post({ jsonrpc: '2.0', id: Date.now(), method: 'tools/call', params: { name, arguments: args } });
      } catch (error) {
        if (attempt || !/HTTP (400|404)/.test(error.message)) throw error;
        this.sessionId = null;
      }
    }
    throw new Error('Ombre MCP call failed after session refresh');
  }

  // 网关用：拉 OB 的 tools/list（供心潮念合并暴露 OB 记忆工具）。
  // 带会话刷新重试——OB 重启后旧 session 失效，第一次会失败；不重试的话 tools/list 会
  // 瞬态只剩心潮 3 个工具（OB 工具消失），直到下次拉取。tools/list 只读、重试安全。
  async listTools() {
    for (let attempt = 0; attempt < 2; attempt += 1) {
      try {
        await this.initialize();
        const raw = await this.post({ jsonrpc: '2.0', id: Date.now(), method: 'tools/list', params: {} });
        return raw?.result?.tools ?? raw?.tools ?? [];
      } catch (error) {
        this.sessionId = null;
        if (attempt) throw error;
      }
    }
    return [];
  }

  async recentMaterial(drives = []) {
    return (await this.recentMaterialWithRefs(drives)).text;
  }

  async recentMaterialWithRefs(drives = []) {
    const result = await this.call('breath', {
      query: withDriveHint('近期重要记忆、情绪、关系变化和未完成事项', drives),
      max_results: this.config.breathMaxResults,
      max_tokens: this.config.breathMaxTokens
    });
    return materialWithRefs(extractText(result), 10000);
  }

  async daytimeMaterial(drives = []) {
    return (await this.daytimeMaterialWithRefs(drives)).text;
  }

  async daytimeMaterialWithRefs(drives = []) {
    const result = await this.call('breath', {
      query: withDriveHint('白天自然浮现的近期记忆、具体细节、未说完的话和当下牵挂；不要返回系统配置或技术信息', drives),
      max_results: this.config.breathMaxResults,
      max_tokens: this.config.breathMaxTokens
    });
    return materialWithRefs(extractText(result), 10000);
  }

  // 自主念头用的材料：比日间浮现更短，只要能让念头落到具体的事上。
  async thoughtMaterial(drives = []) {
    return (await this.thoughtMaterialWithRefs(drives)).text;
  }

  async thoughtMaterialWithRefs(drives = []) {
    const result = await this.call('breath', {
      query: withDriveHint('此刻自然想起的一件具体的事：最近的共同经历、说过的话或还惦记着的东西；不要返回系统配置、部署或技术信息', drives),
      max_results: Math.max(1, Math.min(3, Number(this.config.breathMaxResults) || 2)),
      max_tokens: Math.max(200, Math.min(600, Number(this.config.breathMaxTokens) || 400))
    });
    return materialWithRefs(extractText(result), 4000);
  }

  async recentContinuityMaterial(maxTokens = this.config.breathMaxTokens) {
    const result = await this.call('breath', {
      query: [
        '新窗口近期连续性：只返回最近发生了什么，以及仍直接影响现在的人物与关系变化、生活重点和未完成约定。',
        '不要返回核心准则、自我基岩或长期画像；这些由客户端从自己的核心指令和长期记忆单独完整读取。',
        '不要返回部署、代码、接口、密钥、系统日志或已经过期的技术待办。',
      ].join(''),
      max_results: Math.max(3, Math.min(8, Number(this.config.breathMaxResults) || 3)),
      max_tokens: Math.max(200, Math.min(3000, Number(maxTokens) || 1600)),
    });
    return extractText(result).slice(0, 16000);
  }

  // Compatibility alias for older callers.  It intentionally returns only
  // recent continuity; it is not a replacement for repository bedrock.
  async handoffMaterial(maxTokens = this.config.breathMaxTokens) {
    return this.recentContinuityMaterial(maxTokens);
  }

  // 网页记忆星图只读取 pulse 暴露的桶元数据，不读取正文。公开版当前的
  // pulse 是人类可读文本；未来融合版若直接返回结构化 JSON，同一适配器也
  // 会保留 driveSnapshot / driveAffinity 等 3.0 可选字段。
  async memoryMap() {
    if (!this.config.readEnabled) return emptyMemoryMap('not_configured');
    const result = await this.call('pulse', {});
    return parseMemoryMapText(extractText(result));
  }

  async memoryBucketPreview(bucketId, maxLines = 7) {
    if (!this.config.readEnabled) return emptyMemoryPreview(bucketId, 'not_configured');
    const id = String(bucketId ?? '').trim();
    if (!/^[A-Za-z0-9._-]{1,160}$/.test(id)) return emptyMemoryPreview(id, 'invalid_id');
    const url = new URL(this.config.url);
    url.pathname = `/api/bucket-preview/${encodeURIComponent(id)}`;
    url.search = '';
    const headers = { Accept: 'application/json', 'X-Ombre-Caller': 'dynamic-mind' };
    if (this.config.token) headers.Authorization = `Bearer ${this.config.token}`;
    const response = await fetch(url, { headers, signal: AbortSignal.timeout(10000) });
    if (response.status === 404) return emptyMemoryPreview(id, 'not_found');
    if (!response.ok) throw new Error(`Ombre preview failed: HTTP ${response.status}`);
    return parseMemoryPreviewText(JSON.stringify({ ok: true, ...(await response.json()) }), id, maxLines);
  }

  async memoryBucketPreviews(bucketIds = [], maxLines = 7) {
    const ids = [...new Set((Array.isArray(bucketIds) ? bucketIds : [])
      .map(String).map((id) => id.trim()).filter(Boolean))].slice(0, 8);
    const previews = [];
    for (const id of ids) {
      const item = await this.memoryBucketPreview(id, maxLines);
      if (item.available && item.preview) previews.push(item);
    }
    return previews;
  }

  // 用户显式 hold 后，新产出仍走 OB 现有 grow；心潮不按 ID 改写源桶正文。
  async storeHeldOutput(item) {
    if (!this.config.writeEnabled) throw new Error('ombre_write_disabled');
    const content = String(item?.content ?? '').trim();
    if (!content) throw new Error('pending_content_empty');
    const result = await this.call('grow', {
      content,
      source: 'xinchao-pending-hold',
    });
    const text = extractText(result);
    const bucketId = parseGrowBucketIds(text)[0] ?? null;
    if (!bucketId) throw new Error('ombre_grow_missing_bucket_id');
    return bucketId;
  }

  // 只用 OB 已有 trace 记一条来源关系；不改正文、不强制 anchor、不新增 OB 写能力。
  async traceHeldOutputSources(outputBucketId, sourceBucketIds = []) {
    if (!this.config.writeEnabled) throw new Error('ombre_write_disabled');
    const outputId = String(outputBucketId ?? '').trim();
    const sourceIds = [...new Set((Array.isArray(sourceBucketIds) ? sourceBucketIds : [])
      .map(String).map((id) => id.trim()).filter((id) => id && id !== outputId))].slice(0, 8);
    const linked = [];
    for (const sourceId of sourceIds) {
      const result = await this.call('trace', {
        bucket_id: sourceId,
        meaning_append: `心潮延续：这段记忆后来生出一条被用户留下的独处产出（${outputId}）。`,
      });
      const text = extractText(result);
      if (/^(未找到记忆桶|修改失败)/.test(text.trim())) {
        throw new Error(`ombre_trace_failed:${sourceId}`);
      }
      linked.push(sourceId);
    }
    return linked;
  }

  async storeDream(dream) {
    if (!this.config.writeEnabled) return null;
    const content = [
      `梦境：${dream.dream}`,
      `梦境余韵：${dream.residue}`,
      `醒后意识：${dream.awareness}`,
      '说明：这是睡眠结算产生的梦境，不是现实事件；调用外部记忆服务不等于醒来。'
    ].join('\n');
    const result = await this.call('hold', {
      content,
      tags: 'dream',
      importance: 7,
      auto: true,
      source: 'xinchao-dream',
    });
    const text = extractText(result);
    const bucketId = text.match(/[a-f0-9]{12,}/i)?.[0] ?? null;
    // 梦是睡眠结算的残渣，不该作为真实记忆回到 breath（否则下次梦引擎会把旧梦当素材捞出 → 梦吃梦）。
    // 出生即标 dont_surface=1：仍存在 OB、仍显示在梦境页（来自心潮 state），但不进 breath 召回。
    if (bucketId) {
      try { await this.call('trace', { bucket_id: bucketId, dont_surface: 1 }); }
      catch (error) { /* best-effort：标记失败不阻断存梦本身 */ }
    }
    return bucketId;
  }
}

// 把当前最强的几个驱动力拼进 breath 的 query，让"此刻想什么"影响"想起什么"。
//
// 这里只改排序，不改准入：能不能返回仍然由 Ombre 的 admission gate 判定
// （要有原句、词锚或高语义证据）。所以驱动力高不会凭空造出记忆，只会让
// 本来就有证据的那几条里，跟当下状态相关的先浮上来。末尾那句兜底很重要，
// 没有它的话强驱动力会把召回卡死成空。
function withDriveHint(base, drives) {
  const labels = (Array.isArray(drives) ? drives : [])
    .filter((item) => Number(item?.value) >= DRIVE_HINT_MIN)
    .slice(0, DRIVE_HINT_MAX_LABELS)
    .map((item) => String(item?.label ?? '').trim())
    .filter(Boolean);
  if (!labels.length) return base;
  return `${base}。此刻最强的内在状态是${labels.join('、')}，优先浮现与之真正相关的具体记忆；没有直接相关的就照常返回近期重要的`;
}

const DRIVE_HINT_MIN = 0.5;
const DRIVE_HINT_MAX_LABELS = 3;

// 从 breath 输出里把每条桶表头的 [domain:...] 解析出来，供记忆共振算亲和度。
// OB 2.6.5+（breath-meta）在表头带 domain/tags；老输出没有时返回空数组，不影响。
export function parseSurfacedDomains(text) {
  const domains = [];
  const re = /\[domain:([^\]]*)\]/g;
  let match;
  while ((match = re.exec(String(text ?? ''))) !== null) {
    for (const part of match[1].split(',')) {
      const value = part.trim();
      if (value) domains.push(value);
    }
  }
  return domains;
}

// OB breath 2.6.5+ 每个浮现桶的表头都带 [bucket_id:...]。
// 只取表头里的 ID，不从正文猜，避免把记忆里偶然出现的字符串误当成来源桶。
// 老版 OB 没有这个元数据时返回空数组，不影响旧调用者。
export function parseSurfacedBucketIds(text) {
  const ids = [];
  const seen = new Set();
  const re = /\[bucket_id:([A-Za-z0-9._-]{1,160})\]/g;
  let match;
  while ((match = re.exec(String(text ?? ''))) !== null) {
    const id = match[1].trim();
    if (id && !seen.has(id)) {
      seen.add(id);
      ids.push(id);
    }
  }
  return ids;
}

export function materialWithRefs(text, maxChars = 10000) {
  const limited = String(text ?? '').slice(0, Math.max(0, Number(maxChars) || 0));
  return {
    text: limited,
    bucketIds: parseSurfacedBucketIds(limited),
    domains: parseSurfacedDomains(limited),
  };
}

// grow 返回的人类可读结果中，真实桶 ID 只出现在“→”或每条 📎/📝 之后。
// 明确排除 batch:g_... 和正文中的偶然字符串，不做宽泛 ID 猜测。
export function parseGrowBucketIds(text) {
  const ids = [];
  const seen = new Set();
  const source = String(text ?? '');
  const patterns = [/(?:→|[📎📝])\s*([A-Za-z0-9._-]{6,160})/g];
  for (const pattern of patterns) {
    let match;
    while ((match = pattern.exec(source)) !== null) {
      const id = match[1].trim();
      if (!seen.has(id)) {
        seen.add(id);
        ids.push(id);
      }
    }
  }
  return ids;
}

function parseMcp(text) {
  const data = text.split('\n').find((line) => line.startsWith('data:'))?.slice(5).trim() ?? text;
  return JSON.parse(data);
}

function extractText(result) {
  const content = result?.result?.content ?? result?.content ?? [];
  return content.filter((part) => part.type === 'text').map((part) => part.text).join('\n');
}

function emptyMemoryMap(reason = 'empty') {
  return {
    schemaVersion: 2,
    generatedAt: new Date().toISOString(),
    available: false,
    reason,
    total: 0,
    stats: {},
    stars: [],
    edges: [],
    capabilities: {
      explicitRelations: false,
      driveSnapshots: false,
      driveAffinity: false,
      timestamps: false,
    },
  };
}

function emptyMemoryPreview(id, reason = 'empty') {
  return { schemaVersion: 1, available: false, reason, id: String(id ?? ''), preview: '', lineCount: 0, truncated: false };
}

export function parseMemoryPreviewText(raw, expectedId = '', maxLines = 7) {
  const text = String(raw ?? '').trim();
  if (!text) return emptyMemoryPreview(expectedId, 'empty');
  try {
    const parsed = JSON.parse(text);
    if (!parsed?.ok) return emptyMemoryPreview(expectedId, String(parsed?.error || 'not_found'));
    const id = String(parsed.id ?? expectedId).trim();
    if (expectedId && id !== expectedId) return emptyMemoryPreview(expectedId, 'id_mismatch');
    const lineLimit = Math.max(1, Math.min(7, Number(maxLines) || 7));
    const preview = String(parsed.preview ?? '').split(/\r?\n/).slice(0, lineLimit).join('\n').slice(0, 1400);
    return {
      schemaVersion: 1,
      available: Boolean(preview),
      reason: preview ? undefined : 'empty',
      id,
      preview,
      lineCount: preview ? preview.split(/\r?\n/).length : 0,
      truncated: Boolean(parsed.truncated),
    };
  } catch {
    return emptyMemoryPreview(expectedId, 'invalid_response');
  }
}

function numberOrNull(value) {
  if (value == null || value === '') return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function normalizeStar(star = {}) {
  const id = String(star.id ?? star.bucketId ?? star.bucket_id ?? '').trim();
  if (!id) return null;
  const pinned = Boolean(star.pinned || star.bucketType === 'permanent' || star.type === 'permanent');
  const driveSnapshot = star.driveSnapshot ?? star.drive_snapshot ?? null;
  const driveAffinity = star.driveAffinity ?? star.drive_affinity ?? null;
  return {
    id,
    title: String(star.title ?? star.name ?? '（无题）').trim() || '（无题）',
    pinned,
    bucketType: String(star.bucketType ?? star.type ?? (pinned ? 'permanent' : 'dynamic')),
    domains: Array.isArray(star.domains) ? star.domains.map(String).filter(Boolean)
      : Array.isArray(star.domain) ? star.domain.map(String).filter(Boolean)
        : String(star.domain ?? '').split(/[,，]/).map((item) => item.trim()).filter(Boolean),
    valence: numberOrNull(star.valence),
    arousal: numberOrNull(star.arousal),
    importance: numberOrNull(star.importance),
    weight: numberOrNull(star.weight ?? star.score),
    tags: Array.isArray(star.tags) ? star.tags.map(String).filter(Boolean)
      : String(star.tags ?? '').split(/[,，]/).map((item) => item.trim()).filter(Boolean),
    createdAt: star.createdAt ?? star.created_at ?? null,
    updatedAt: star.updatedAt ?? star.updated_at ?? null,
    lastActiveAt: star.lastActiveAt ?? star.last_active ?? null,
    activationCount: numberOrNull(star.activationCount ?? star.activation_count),
    anchored: Boolean(star.anchored),
    resolved: Boolean(star.resolved),
    historical: star.historical == null ? !driveSnapshot : Boolean(star.historical),
    meaningCount: Array.isArray(star.meaning) ? star.meaning.length : Number(star.meaningCount ?? 0) || 0,
    driveSnapshot: driveSnapshot && typeof driveSnapshot === 'object' ? driveSnapshot : null,
    driveAffinity: driveAffinity && typeof driveAffinity === 'object' ? driveAffinity : null,
  };
}

function buildMapEdges(stars, minShared = 3, maxPerNode = 6) {
  const byTag = new Map();
  stars.forEach((star, index) => star.tags.forEach((tag) => {
    if (!byTag.has(tag)) byTag.set(tag, []);
    byTag.get(tag).push(index);
  }));
  const pairs = new Map();
  for (const indexes of byTag.values()) {
    if (indexes.length > stars.length * .5) continue;
    for (let left = 0; left < indexes.length; left += 1) {
      for (let right = left + 1; right < indexes.length; right += 1) {
        const key = `${indexes[left]}|${indexes[right]}`;
        pairs.set(key, (pairs.get(key) || 0) + 1);
      }
    }
  }
  const candidates = [];
  for (const [key, shared] of pairs) {
    if (shared < minShared) continue;
    const [left, right] = key.split('|').map(Number);
    const denominator = Math.min(stars[left].tags.length, stars[right].tags.length) || 1;
    candidates.push({ left, right, shared, similarity: Math.min(1, shared / denominator) });
  }
  candidates.sort((a, b) => b.similarity - a.similarity || b.shared - a.shared);
  const degree = new Array(stars.length).fill(0);
  const edges = [];
  for (const candidate of candidates) {
    if (degree[candidate.left] >= maxPerNode || degree[candidate.right] >= maxPerNode) continue;
    degree[candidate.left] += 1;
    degree[candidate.right] += 1;
    edges.push({
      source: stars[candidate.left].id,
      target: stars[candidate.right].id,
      similarity: Number(candidate.similarity.toFixed(2)),
      kind: 'tag-derived',
      label: `${candidate.shared} 个共同标签`,
    });
  }
  return edges;
}

function normalizeEdges(edges, stars) {
  const ids = new Set(stars.map((star) => star.id));
  return (Array.isArray(edges) ? edges : []).flatMap((edge) => {
    const source = String(edge?.source ?? '').trim();
    const target = String(edge?.target ?? '').trim();
    if (!source || !target || source === target || !ids.has(source) || !ids.has(target)) return [];
    return [{
      source,
      target,
      similarity: Math.max(0, Math.min(1, Number(edge.similarity ?? edge.weight ?? 0) || 0)),
      kind: edge.kind === 'semantic' || edge.kind === 'tag-derived' ? edge.kind : 'explicit',
      label: String(edge.label ?? '').slice(0, 120),
    }];
  });
}

export function parseMemoryMapText(raw) {
  const text = String(raw ?? '').trim();
  if (!text) return emptyMemoryMap('empty');

  // 3.0 结构化输出优先；公开版旧 pulse 继续走下方无损文本适配。
  try {
    const parsed = JSON.parse(text);
    const sourceStars = parsed.stars ?? parsed.nodes;
    if (Array.isArray(sourceStars)) {
      const stars = sourceStars.map(normalizeStar).filter(Boolean);
      const explicitEdges = normalizeEdges(parsed.edges ?? parsed.links, stars);
      const capabilities = {
        explicitRelations: explicitEdges.length > 0,
        driveSnapshots: stars.some((star) => star.driveSnapshot),
        driveAffinity: stars.some((star) => star.driveAffinity),
        timestamps: stars.some((star) => star.createdAt || star.updatedAt),
      };
      return {
        schemaVersion: Number(parsed.schemaVersion ?? 2),
        generatedAt: String(parsed.generatedAt ?? new Date().toISOString()),
        available: true,
        total: stars.length,
        stats: parsed.stats && typeof parsed.stats === 'object' ? parsed.stats : {},
        stars,
        edges: explicitEdges.length ? explicitEdges : buildMapEdges(stars),
        capabilities,
      };
    }
  } catch {
    // 人类可读 pulse 不是 JSON，继续解析；不把解析失败当服务故障。
  }

  const stats = {};
  for (const [key, label] of [['pinned', '固化桶'], ['dynamic', '动态桶'], ['archived', '归档桶']]) {
    const match = text.match(new RegExp(`${label}[:：]\\s*(\\d+)`));
    if (match) stats[key] = Number(match[1]);
  }
  const size = text.match(/总占用[:：]\s*([\d.]+\s*\w+)/);
  if (size) stats.size = size[1];

  const stars = [];
  const line = /((?:\uD83D\uDCCC)?)\s*\[([0-9a-f]+)\]\s*《([^》]*)》([^\n]*)/gi;
  let match;
  while ((match = line.exec(text)) !== null) {
    const [, pin, id, title, tail] = match;
    const domain = (tail.match(/主题[:：]\s*([^\s]+)/) || [])[1] || '';
    const emotion = tail.match(/情感[:：]\s*V(-?[\d.]+)\/A(-?[\d.]+)/);
    const importance = (tail.match(/重要[:：]\s*([\d.]+)/) || [])[1];
    const weight = (tail.match(/权重[:：]\s*([\d.]+)/) || [])[1];
    const tags = (tail.match(/标签[:：]\s*(.+)$/) || [])[1] || '';
    stars.push(normalizeStar({
      id,
      title,
      pinned: pin.length > 0,
      bucketType: pin.length > 0 ? 'permanent' : 'dynamic',
      domains: domain.split(/[,，]/).filter(Boolean),
      valence: emotion ? Number(emotion[1]) : null,
      arousal: emotion ? Number(emotion[2]) : null,
      importance: importance ? Number(importance) : null,
      weight: weight ? Number(weight) : null,
      tags: tags.split(/[,，]/).map((item) => item.trim()).filter(Boolean),
      historical: true,
    }));
  }
  const filteredStars = stars.filter(Boolean);
  return {
    schemaVersion: 2,
    generatedAt: new Date().toISOString(),
    available: true,
    total: filteredStars.length,
    stats,
    stars: filteredStars,
    edges: buildMapEdges(filteredStars),
    capabilities: {
      explicitRelations: false,
      driveSnapshots: false,
      driveAffinity: false,
      timestamps: false,
    },
  };
}
