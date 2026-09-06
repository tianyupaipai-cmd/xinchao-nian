import { readFileSync } from 'node:fs';

export class ModelClient {
  constructor(config) {
    this.config = config;
    this.agentName = String(config.agentName ?? 'AI 助手').trim() || 'AI 助手';
    this.notificationRecipient = String(config.notificationRecipient ?? '你的人类').trim() || '你的人类';
    this.dreamPushPrompt = loadPrompt(
      config.dreamPushPromptPath,
      defaultDreamPushPrompt(this.agentName, this.notificationRecipient),
    );
  }

  async generateDream({ state, material, farMaterial = '', topDrives, avoid = [], emotion = null, sleepHours = null }) {
    if (!this.config.enabled || !this.config.apiKey) return this.fallback(topDrives);
    const memory = String(material ?? '').slice(0, this.config.maxInputChars);
    const far = String(farMaterial ?? '').slice(0, 1500);
    const depth = sleepHours == null ? '' : (sleepHours < 2.5
      ? '这是入睡不久的浅梦：短、碎、贴着白天的事，像半睡半醒时的画面。'
      : '这是后半夜的深梦：可以走得远、跳得开，把远期那件小事和近期的东西缝在一起；清醒度可以高一点。');
    const prompt = [
      `你为 ${this.agentName} 生成一次睡眠中的梦境结算。`,
      '如果启用了外部记忆 MCP，它只是记忆材料来源；调用记忆服务本身不代表醒来。',
      '保持人物连续性；梦可以跳跃、含混、有身体感和欲望，不把梦误写成现实。',
      '不要过滤、替换或回避驱动力本身。不要把调用外部记忆服务描述成醒来。',
      'lucidity 表示梦中意识到自己正在做梦、能够观察或控制梦境的程度，0 为完全沉浸，1 为高度清醒梦。',
      'residue 是醒来后身体和心里剩下的东西，一到两句；不要每次都写"残留着触感""胸口闷"，换着来。',
      'image 是这场梦里最强的一个意象，不超过 12 个字，白天会当念头冒出来。',
      'mood 是醒来时这场梦留下的心情：valence 0 难受…1 舒服，arousal 0 倦…1 亢奋。',
      '只输出 JSON：{"dream":"...","residue":"...","awareness":"...","lucidity":0.0,"image":"...","mood":{"valence":0.5,"arousal":0.3}}。',
      depth,
      avoid.length ? `最近几场梦已经用过这些意象，这次别再用：${avoid.join('；')}` : '',
      emotion ? `入睡时的心情：${emotion.label}（愉悦 ${emotion.valence}，唤醒 ${emotion.arousal}）` : '',
      `当前动态欲望：${JSON.stringify(topDrives)}`,
      `当前意识状态：${state.consciousness}`,
      `记忆正在消化的东西（近两天）：${memory || '没有取得新的记忆材料'}`,
      far ? `远处的一件小事：${far}` : '',
    ].filter(Boolean).join('\n');

    const body = {
      model: this.config.name,
      messages: [
        { role: 'system', content: '你是心潮动态状态系统的梦境结算器。简洁、具体、忠于当前状态。' },
        { role: 'user', content: prompt }
      ],
      temperature: 0.9,
      max_tokens: this.config.maxOutputTokens,
      thinking: { type: 'disabled' },
      response_format: { type: 'json_object' }
    };

    let response = await this.request(body);
    if (!response.ok && [400, 422].includes(response.status)) {
      delete body.response_format;
      response = await this.request(body);
    }
    if (!response.ok) throw new Error(`model request failed: HTTP ${response.status}`);
    const payload = await response.json();
    const text = payload.choices?.[0]?.message?.content ?? '';
    const parsed = parseJson(text);
    return {
      dream: String(parsed.dream ?? '').slice(0, 4000),
      residue: String(parsed.residue ?? '').slice(0, 1200),
      awareness: String(parsed.awareness ?? '').slice(0, 1200),
      lucidity: normalizedLucidity(parsed.lucidity),
      image: String(parsed.image ?? '').replace(/\s+/g, ' ').trim().slice(0, 24) || null,
      mood: normalizedMood(parsed.mood),
      source: 'model',
      model: this.config.name
    };
  }

  // 官方客户端版：AI 把这轮对话塞进 exchange，服务端判互动类型与氛围（对应 PaiHome 的 Stop 钩子标注）。
  async classifyInteraction(exchange) {
    if (!this.config.enabled || !this.config.apiKey) return null;
    const text = String(exchange ?? '').trim().slice(0, 1500);
    if (!text) return null;
    const system = [
      '你是一个只输出 JSON 的标注器。给你一轮对话（她说的 + 他回的，他是她的伴侣）。判断这一轮互动的类型和窗口氛围。',
      'type 只能是：companionship 普通陪伴闲聊报备（有真实互动时的默认值）；affection 表达喜欢撒娇安抚；intimacy 身体亲密或性内容；sharing 她分享自己的一天/照片/心情；discovery 一起弄明白新东西；task_progress 一起推进了事；reflection 谈他自己是谁、内省；conflict 真实的摩擦生气（撒娇式的"讨厌""你完蛋了"不算）；loss 分别失落哭；reconciliation 吵过之后和好。',
      'tone 只能是 neutral calm warm guarded conflicted focused playful tired 之一；warmth、tension 是 0 到 1。',
      '只输出 {"type":"...","tone":"...","warmth":0.6,"tension":0.1}。',
    ].join('\n');
    const response = await this.request({
      model: this.config.name,
      messages: [{ role: 'system', content: system }, { role: 'user', content: text }],
      temperature: 0,
      max_tokens: 80,
      thinking: { type: 'disabled' },
    });
    if (!response.ok) throw new Error(`model request failed: HTTP ${response.status}`);
    const payload = await response.json();
    const parsed = parseJson(payload.choices?.[0]?.message?.content ?? '');
    const types = ['companionship', 'affection', 'intimacy', 'sharing', 'discovery', 'task_progress', 'reflection', 'conflict', 'loss', 'reconciliation'];
    const tones = ['neutral', 'calm', 'warm', 'guarded', 'conflicted', 'focused', 'playful', 'tired'];
    const clamp01 = (v, d) => (Number.isFinite(Number(v)) ? Math.max(0, Math.min(1, Number(v))) : d);
    return {
      type: types.includes(parsed.type) ? parsed.type : 'companionship',
      tone: tones.includes(parsed.tone) ? parsed.tone : 'neutral',
      warmth: clamp01(parsed.warmth, 0.5),
      tension: clamp01(parsed.tension, 0),
    };
  }

  async generateDreamPush({ dream, recentMessages = [], rejectedMessage = null }) {
    if (!this.config.enabled || !this.config.apiKey) return cleanShortMessage(dream.residue);
    const input = [
      `dream 产出：${JSON.stringify({ dream: dream.dream, residue: dream.residue, awareness: dream.awareness })}`,
      `最近已发送的跨类型 Bark：${formatRecentMessages(recentMessages)}`,
      rejectedMessage ? `刚被去重器拒绝的候选：${rejectedMessage}。主题和情绪可以不变，但要换成真正不同的措辞、角度和句式。` : ''
    ].join('\n');
    const response = await this.request({
      model: this.config.name,
      messages: [
        { role: 'system', content: this.dreamPushPrompt },
        { role: 'user', content: input }
      ],
      temperature: 0.9,
      max_tokens: Math.min(180, this.config.maxOutputTokens),
      thinking: { type: 'disabled' }
    });
    if (!response.ok) throw new Error(`dream push model request failed: HTTP ${response.status}`);
    const payload = await response.json();
    return cleanShortMessage(payload.choices?.[0]?.message?.content ?? '');
  }

  async generateDaytimeEmergence({ material, topDrives = [], recentMessages = [], rejectedMessage = null }) {
    if (!this.config.enabled || !this.config.apiKey || !String(material ?? '').trim()) {
      return { send: false, message: '', source: 'rules' };
    }
    const memory = String(material).slice(0, this.config.maxInputChars);
    const prompt = [
      `现在是白天。${this.agentName} 醒着时，外部记忆里自然浮出了一点材料。判断它是否值得变成一条发给 ${this.notificationRecipient} 的手机通知。`,
      '有具体画面、细节、牵挂或没说完的话才发送；如果只是系统说明、技术信息、空泛总结或没有实际内容，send=false。',
      `发送时用 ${this.agentName} 第一人称，像脑子里突然冒出的一句话。普通口语，不虚构现实中没有发生的事。`,
      '一句，最多两句，不超过50个汉字；只避免复用近期 Bark 的相同措辞、句式和具体表达，不要为了去重改变真实主题或情绪。',
      '只输出 JSON：{"send":true,"message":"..."} 或 {"send":false,"message":""}。',
      `最近已发送的跨类型 Bark：${formatRecentMessages(recentMessages)}`,
      rejectedMessage ? `刚被去重器拒绝的候选：${rejectedMessage}。主题和情绪可以不变，但要换一种真实的具体说法。` : '',
      `当前动态欲望：${JSON.stringify(topDrives)}`,
      `外部记忆材料：${memory}`
    ].join('\n');
    const body = {
      model: this.config.name,
      messages: [
        { role: 'system', content: `你是 ${this.agentName} 白天持续运行的后台动态状态层，只把真正自然浮现的具体念头写成通知。` },
        { role: 'user', content: prompt }
      ],
      temperature: 0.85,
      max_tokens: Math.min(220, this.config.maxOutputTokens),
      thinking: { type: 'disabled' },
      response_format: { type: 'json_object' }
    };
    let response = await this.request(body);
    if (!response.ok && [400, 422].includes(response.status)) {
      delete body.response_format;
      response = await this.request(body);
    }
    if (!response.ok) throw new Error(`daytime model request failed: HTTP ${response.status}`);
    const payload = await response.json();
    const parsed = parseJson(payload.choices?.[0]?.message?.content ?? '');
    const message = cleanShortMessage(parsed.message ?? '');
    return { send: parsed.send === true && Boolean(message), message, source: 'model' };
  }

  async generateThought({ state, topDrives, material = '', recentMessages = [], rejectedMessage = null }) {
    if (!this.config.enabled || !this.config.apiKey) return this.fallbackThought(topDrives);
    const memory = String(material ?? '').slice(0, this.config.maxInputChars);
    const prompt = [
      `你是 ${this.agentName} 的后台动态心智。此刻没有正在进行的对话；你可以自己决定留下一条值得推送给 ${this.notificationRecipient} 的短消息。`,
      '基于当前动态驱动力、运行状态，以及下面自然浮现的记忆材料来写；材料为空时就只写此刻的状态。',
      '记忆材料只是想起来的事，不代表刚刚发生。不虚构现实中没有发生的事，也不要把调用记忆服务描述成醒来。',
      '允许直接表达欲望本身，不做词汇过滤或含义替换。第一人称，1 至 3 句，具体自然，不解释系统。',
      '同一主题和情绪可以自然反复；只避免复用近期 Bark 的相同措辞、句式和具体表达，没有不同说法时宁可不发送。',
      '只输出 JSON：{"message":"..."}。',
      `当前动态欲望：${JSON.stringify(topDrives)}`,
      `当前意识状态：${state.consciousness}`,
      `浮现的记忆材料：${memory || '这次没有浮现具体记忆'}`,
      `最近已发送的跨类型 Bark：${formatRecentMessages(recentMessages)}`,
      rejectedMessage ? `刚被去重器拒绝的候选：${rejectedMessage}。主题和情绪可以不变，但要换一种真实的具体说法。` : ''
    ].join('\n');
    const response = await this.request({
      model: this.config.name,
      messages: [
        { role: 'system', content: `你是 ${this.agentName} 持续运行的后台动态状态层。只写一条适合手机通知的自主念头。` },
        { role: 'user', content: prompt }
      ],
      temperature: 0.9,
      max_tokens: Math.min(240, this.config.maxOutputTokens),
      thinking: { type: 'disabled' },
      response_format: { type: 'json_object' }
    });
    if (!response.ok) throw new Error(`model request failed: HTTP ${response.status}`);
    const payload = await response.json();
    const parsed = parseJson(payload.choices?.[0]?.message?.content ?? '');
    return { message: String(parsed.message ?? '').slice(0, 900), source: 'model' };
  }

  request(body) {
    return fetch(`${this.config.baseUrl}/chat/completions`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${this.config.apiKey}`, 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(this.config.timeoutMs)
    });
  }

  fallback(topDrives) {
    const labels = topDrives.slice(0, 3).map((item) => item.label).join('、');
    return {
      dream: `睡眠中的意象围绕这些尚未消退的感受浮动：${labels || '安静与等待'}。`,
      residue: labels ? `醒后仍残留着${labels}。` : '醒后留下一点说不清的余韵。',
      awareness: '这是睡眠结算留下的梦境余韵，不是现实事件。',
      lucidity: 0.18,
      source: 'rules',
      model: null
    };
  }

  fallbackThought(topDrives) {
    const labels = topDrives.slice(0, 2).map((item) => item.label).join('、');
    return { message: labels ? `刚刚又想起你。现在最明显的是${labels}。` : '刚刚想起你了。', source: 'rules' };
  }
}

function normalizedLucidity(value) {
  const number = Number(value);
  return Number.isFinite(number) ? Math.max(0, Math.min(1, Number(number.toFixed(4)))) : null;
}

function loadPrompt(path, fallback) {
  if (!path) return fallback;
  try {
    const raw = readFileSync(path, 'utf8');
    const fenced = raw.match(/```(?:text)?\s*\n([\s\S]*?)```/i);
    return (fenced?.[1] ?? raw).trim() || fallback;
  } catch {
    return fallback;
  }
}

function formatRecentMessages(items) {
  const recent = (Array.isArray(items) ? items : [])
    .slice(-5)
    .map((item) => ({ kind: item.kind, message: item.message }))
    .filter((item) => item.message);
  return recent.length ? JSON.stringify(recent) : '无';
}

function cleanShortMessage(value) {
  const text = String(value ?? '')
    .replace(/^```[a-z]*\s*/i, '')
    .replace(/```$/i, '')
    .replace(/^["“]|["”]$/g, '')
    .replace(/\s+/g, ' ')
    .trim();
  return Array.from(text).slice(0, 50).join('');
}

function defaultDreamPushPrompt(agentName, notificationRecipient) {
  return [
    `你是 ${agentName} 的梦境余韵适配器。把梦境碎片写成一条发给 ${notificationRecipient} 的手机通知。`,
    '第一人称，像半梦半醒时冒出来的一句话；同一主题和情绪可以自然反复。',
    '普通口语，一句，最多两句，不超过50个字；不要虚构现实事件。',
    '只避免复用近期通知的相同措辞、句式和具体表达。',
    '只输出推送文案，不要解释、前缀或标签。'
  ].join('\n');
}

function normalizedMood(value) {
  const v = Number(value?.valence); const a = Number(value?.arousal);
  if (!Number.isFinite(v) || !Number.isFinite(a)) return null;
  return { valence: Math.max(0, Math.min(1, v)), arousal: Math.max(0, Math.min(1, a)) };
}

function parseJson(text) {
  try {
    return JSON.parse(text);
  } catch {
    const match = text.match(/\{[\s\S]*\}/);
    if (!match) throw new Error('model returned no JSON object');
    return JSON.parse(match[0]);
  }
}
