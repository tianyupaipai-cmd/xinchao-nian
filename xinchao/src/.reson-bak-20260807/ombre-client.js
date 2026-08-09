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
            clientInfo: { name: 'xinchao-dynamic-mind', version: '2.4.0' },
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

  async recentMaterial(drives = []) {
    const result = await this.call('breath', {
      query: withDriveHint('近期重要记忆、情绪、关系变化和未完成事项', drives),
      max_results: this.config.breathMaxResults,
      max_tokens: this.config.breathMaxTokens
    });
    return extractText(result).slice(0, 10000);
  }

  async daytimeMaterial(drives = []) {
    const result = await this.call('breath', {
      query: withDriveHint('白天自然浮现的近期记忆、具体细节、未说完的话和当下牵挂；不要返回系统配置或技术信息', drives),
      max_results: this.config.breathMaxResults,
      max_tokens: this.config.breathMaxTokens
    });
    return extractText(result).slice(0, 10000);
  }

  // 自主念头用的材料：比日间浮现更短，只要能让念头落到具体的事上。
  async thoughtMaterial(drives = []) {
    const result = await this.call('breath', {
      query: withDriveHint('此刻自然想起的一件具体的事：最近的共同经历、说过的话或还惦记着的东西；不要返回系统配置、部署或技术信息', drives),
      max_results: Math.max(1, Math.min(3, Number(this.config.breathMaxResults) || 2)),
      max_tokens: Math.max(200, Math.min(600, Number(this.config.breathMaxTokens) || 400))
    });
    return extractText(result).slice(0, 4000);
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
    return text.match(/[a-f0-9]{12,}/i)?.[0] ?? null;
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

function parseMcp(text) {
  const data = text.split('\n').find((line) => line.startsWith('data:'))?.slice(5).trim() ?? text;
  return JSON.parse(data);
}

function extractText(result) {
  const content = result?.result?.content ?? result?.content ?? [];
  return content.filter((part) => part.type === 'text').map((part) => part.text).join('\n');
}
