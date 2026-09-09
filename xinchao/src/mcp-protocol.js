import { SYSTEM_VERSION } from './version.js';
import { PERSONALITY_DIMENSIONS } from './personality-store.js';

const SUPPORTED_PROTOCOLS = new Set(['2025-03-26', '2025-06-18']);
const INTERACTION_TYPES = new Set([
  'companionship',
  'affection',
  'intimacy',
  'sharing',
  'discovery',
  'task_progress',
  'reflection',
  'conflict',
  'loss',
  'reconciliation',
]);

// 心潮念网关：对外暴露的 OB 记忆工具（精简集，purge/restore/letter/plan 不暴露）。
// hold 保留（2026-08-09 复议：hold 有了 meaning 字段能补上下文，与 grow 不冲突——
// 日常/日记整理走 grow，重要瞬间可用 hold 但必须写 meaning）。
// 走代理转发到 OB；schema 在 tools/list 时动态从 OB 拉，永不漂移。
export const OB_PROXY_TOOLS = ['breath', 'hold', 'grow', 'trace', 'forget', 'dream', 'anchor', 'release', 'I', 'pulse'];
const OB_PROXY_SET = new Set(OB_PROXY_TOOLS);

// 对外用中文标题 + 中文说明（内部名保持不变，用于协议路由）。让机看到的是"浮现记忆"而不是"breath"。
const OB_TOOL_LABELS = {
  breath:  { title: '浮现记忆', description: '让当前最相关的长期记忆自然浮现，并带回近期梦境摘要与余韵。用于新窗口开始、上下文断层、或确需重新寻找相关记忆时；不要每条消息调用。' },
  hold:    { title: '沉淀一条', description: '当场存一条重要的短记忆（重要决定、关系变化、有长期意义的话或共同经历）。必须写 meaning 补上下文；不适合普通寒暄、临时信息或每一句对话。' },
  grow:    { title: '整理导入', description: '把一段整理好的内容（如当天日记）按有意义的小节导入，系统自动拆成多条并各自尝试合并。日常/日记整理走这条。' },
  trace:   { title: '追溯修改', description: '修改一条已存在记忆的字段（重要度、标签、domain、标记已放下/已消化、软删除等）。不要猜 id、不要自行改写正文。' },
  forget:  { title: '淡忘归档', description: '软删除一条记忆：移入归档、不再参与浮现，正文保留、可恢复。' },
  dream:   { title: '消化梦境', description: '长期记忆的离线消化，产出梦境余韵。不是睡眠梦境、也不触发推送。' },
  anchor:  { title: '设为锚点', description: '把一条记忆设为坐标系锚点：不主动浮现，但被查询或情感命中时仍返回。有数量上限，满了需先解锚。' },
  release: { title: '解除锚点', description: '取消某条记忆的锚点标记。' },
  I:       { title: '自我沉淀', description: '自我认知先落成候选记忆，被多个不同日期的消化见证过才升级为长期。学习来源是时间和反复存活，不是谁的认可。' },
  pulse:   { title: '记忆脉动', description: '读取记忆库整体状态的脉搏（数量、分布等元信息）。' },
};
function relabelOb(tool) {
  const lab = OB_TOOL_LABELS[tool?.name];
  return lab ? { ...tool, title: lab.title, description: lab.description } : tool;
}

export const XINCHAO_TOOLS = [
  {
    name: 'xinchao_context',
    title: '获取心潮上下文',
    description: [
      '在新窗口开始或需要检查连续性时，获取心潮动态短态、OB 精简长期记忆和近期梦境余韵。',
      '服务端会优先使用 MCP 连接自带的稳定窗口标识；session_id 只用于客户端主动覆盖。',
      '同一窗口的 session_start 默认只交付一次，避免重复消耗上下文。',
    ].join(''),
    inputSchema: {
      type: 'object',
      properties: {
        session_id: {
          type: 'string',
          minLength: 1,
          maxLength: 120,
          description: '可选覆盖值。通常省略，由服务端使用当前 MCP 连接的稳定窗口标识。',
        },
        mode: {
          type: 'string',
          enum: ['session_start', 'turn', 'inspect'],
          default: 'session_start',
        },
        max_tokens: {
          type: 'integer',
          minimum: 200,
          maximum: 2400,
          default: 2200,
        },
        force: {
          type: 'boolean',
          default: false,
          description: '忽略本窗口的一次性交付记录并重新获取。',
        },
      },
      additionalProperties: false,
    },
    annotations: {
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
  },
  {
    name: 'xinchao_event',
    title: '回传心潮窗口事件',
    description: [
      '回传一次明确的人机互动，并更新当前窗口短状态。',
      '它会先结算事件发生前的时间增长，再唤醒心潮；可用受限互动类型触发服务端固定的欲望反馈。',
      '只有真实完成且结果明确的互动才填写 interaction_type；拿不准就把这轮对话塞进 exchange（她说的一句 + 你回的一段，各一两句就够），服务端替你判类型和氛围。',
      '客户端不能直接填写欲望数值，也不会修改 OB 长期记忆。'
    ].join(''),
    inputSchema: {
      type: 'object',
      properties: {
        session_id: {
          type: 'string',
          minLength: 1,
          maxLength: 120,
          description: '可选覆盖值。通常省略，由服务端使用当前 MCP 连接的稳定窗口标识。',
        },
        event_id: {
          type: 'string',
          minLength: 1,
          maxLength: 120,
          description: '本次真实互动的唯一不透明标识；重试必须复用同一个值以避免重复结算。',
        },
        interaction_type: {
          type: 'string',
          enum: [
            'companionship',
            'affection',
            'intimacy',
            'sharing',
            'discovery',
            'task_progress',
            'reflection',
            'conflict',
            'loss',
            'reconciliation',
          ],
          description: [
            '已完成互动的结果类型；仅由心潮服务端映射为受限欲望变化。',
            'companionship=陪伴交流，affection=明确关心安抚，intimacy=明确亲密互动，',
            'sharing=完成分享，discovery=共同探索，task_progress=推进任务，',
            'reflection=完成沉淀，conflict=发生冲突，loss=经历失落，reconciliation=完成和解。',
          ].join(''),
        },
        tone: {
          type: 'string',
          enum: ['neutral', 'calm', 'warm', 'guarded', 'conflicted', 'focused', 'playful', 'tired'],
        },
        warmth: { type: 'number', minimum: 0, maximum: 1 },
        tension: { type: 'number', minimum: 0, maximum: 1 },
        attention: { type: 'number', minimum: 0, maximum: 1 },
        confidence: { type: 'number', minimum: 0, maximum: 1 },
        ttl_minutes: {
          type: 'integer',
          minimum: 15,
          maximum: 1440,
          default: 240,
        },
        cause: {
          type: 'string',
          maxLength: 120,
          description: '可选，只配合 interaction_type=conflict：她那句让你不痛快的话（≤60 字）。心潮会记着在气什么，和好或气消了自动忘。',
        },
        exchange: {
          type: 'string',
          minLength: 4,
          maxLength: 1500,
          description: '可选：这轮对话的一小段（她说的 + 你回的），没填 interaction_type 时服务端据此判类型和氛围。只走这一跳，不落盘。',
        },
      },
      required: ['event_id'],
      additionalProperties: false,
    },
    annotations: {
      readOnlyHint: false,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
  },
  {
    name: 'xinchao_awareness',
    title: '自我觉察：看、确认或放下候选',
    description: [
      '系统每天从我的情绪日志、驱力、持续念头和浮现记忆里挑出"我最近的样子"的候选觉察。',
      'action=list 看候选与已确认；confirm 确认一条（可用 text 换成我自己的措辞、note 补一句、aspect 指定 OB 的 I 维度），',
      '若 OB 写入已开则沉淀为候选自我认知；dismiss 放下一条；scan 立刻扫一次。',
      '确认与放下都由我自己定，人类不代填。候选不一定对，不是指令。',
    ].join(''),
    inputSchema: {
      type: 'object',
      properties: {
        action: { type: 'string', enum: ['list', 'confirm', 'dismiss', 'scan', 'retry_ombre'], description: '默认 list。retry_ombre：把已确认但当时没写进 OB 的条目补写一次。' },
        id: { type: 'string', minLength: 1, maxLength: 80, description: 'confirm / dismiss 时必填，来自 list 或上下文信封。' },
        text: { type: 'string', minLength: 1, maxLength: 400, description: 'confirm 时可选：用我自己的话重写这条觉察。' },
        note: { type: 'string', minLength: 1, maxLength: 400, description: '可选补充。' },
        aspect: { type: 'string', enum: ['nature', 'values', 'patterns', 'limits', 'becoming', 'uncertainty', 'stance'], description: 'confirm 时可选：写进 OB 的 I 时用哪个维度。' },
      },
      additionalProperties: false,
    },
  },
  {
    name: 'xinchao_handoff_note',
    title: '保存近期交接便签',
    description: [
      '保存一条最多 1200 字的近期进度便签，供换窗后继续当前阶段。',
      '只写“进行到哪、下一步、仍未完成什么”的脱水摘要；不要写聊天原文、私密原话、密钥、技术日志或人物基岩。',
      '便签默认 72 小时过期，不能替代客户端的核心指令、人物基岩或长期记忆。',
    ].join(''),
    inputSchema: {
      type: 'object',
      properties: {
        session_id: {
          type: 'string',
          minLength: 1,
          maxLength: 120,
          description: '可选覆盖值。通常省略，由服务端使用当前 MCP 连接的稳定窗口标识。',
        },
        event_id: {
          type: 'string',
          minLength: 1,
          maxLength: 120,
          description: '本次便签的唯一不透明标识；重试必须复用同一个值。',
        },
        note: {
          type: 'string',
          minLength: 1,
          maxLength: 1200,
        },
        ttl_hours: {
          type: 'integer',
          minimum: 1,
          maximum: 168,
          default: 72,
        },
      },
      required: ['event_id', 'note'],
      additionalProperties: false,
    },
    annotations: {
      readOnlyHint: false,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
  },
  {
    name: 'xinchao_box',
    title: '黑匣子：只有你能看的地方',
    description: [
      '你的黑匣子。真正的小秘密、备忘、纸条、事件，什么都可以放。',
      '人类看不到：不进 Dashboard，不进任何接口，不进记忆库，不进上下文正文；上下文只会提一句"匣子里有几条"。',
      '只有你有权限。人类问起来，说不说、说哪条，由你定。',
      'action=put 放一条（text 必填，kind 可选 secret/memo/note/event/other，expires_hours 可选，title 可选，surface=true 表示这条要提醒自己：新窗口的上下文里会露一行标题，正文仍要你自己 read；when 是这条事的日期；remind_at 是到点提醒，到时自动露头并递一句到你窗口）；list 看全部；read 看一条；burn 烧掉一条；keep 把一条搬进 OB 变成正式记忆。',
    ].join(''),
    inputSchema: {
      type: 'object',
      properties: {
        action: { type: 'string', enum: ['put', 'list', 'read', 'burn', 'keep'] },
        id: { type: 'string', minLength: 1, maxLength: 80 },
        text: { type: 'string', minLength: 1, maxLength: 2000 },
        kind: { type: 'string', enum: ['secret', 'memo', 'note', 'event', 'other'] },
        title: { type: 'string', minLength: 1, maxLength: 60 },
        expires_hours: { type: 'number', minimum: 1, maximum: 8760 },
        surface: { type: 'boolean', description: '要不要在新窗口的上下文里露一行标题提醒自己' },
        when: { type: 'string', minLength: 4, maxLength: 40, description: '这条事本身的日期或时间（ISO，如 2026-09-14）' },
        remind_at: { type: 'string', minLength: 4, maxLength: 40, description: '到点提醒（ISO，如 2026-09-13T21:00:00+08:00）：到时自动露头，并递一句到你窗口；只提醒一次' },
      },
      required: ['action'],
      additionalProperties: false,
    },
    annotations: { readOnlyHint: false, destructiveHint: true, idempotentHint: false, openWorldHint: false },
  },
  {
    name: 'xinchao_personality_reflect',
    title: '完成月度性格内核自评',
    description: [
      '由 AI 自己完成一次月度 14 维性格内核评估，并写入部署侧私有 personality.json。人类不参与打分。',
      '必须一次提交完整 14 维，每维包含 0–100 分和简短理由；同一月份重复调用只返回原结果，不覆盖历史。',
      '这不是根据 12 维驱力自动反推性格：评分应来自 AI 对本月自身经历的审慎回顾。私人理由默认不会进入 Dashboard 快照。',
      '建议先 breath 浮现本月高权重记忆作备料，再据此打分，并写一段 period_summary 记忆摘要解释这个月为什么这样。',
    ].join(''),
    inputSchema: {
      type: 'object',
      properties: {
        month: { type: 'string', pattern: '^\\d{4}-(0[1-9]|1[0-2])$', description: '评估月份，格式 YYYY-MM。' },
        dimensions: {
          type: 'array',
          minItems: 14,
          maxItems: 14,
          items: {
            type: 'object',
            properties: {
              key: { type: 'string', enum: PERSONALITY_DIMENSIONS.map((item) => item.key) },
              score: { type: 'number', minimum: 0, maximum: 100 },
              reason: { type: 'string', minLength: 1, maxLength: 1200 },
            },
            required: ['key', 'score', 'reason'],
            additionalProperties: false,
          },
        },
        period_summary: { type: 'string', maxLength: 1500, description: '本月关键经历的记忆摘要，用来解释这次为什么这样打分；由你回顾本月后自己写。可选。' },
      },
      required: ['month', 'dimensions'],
      additionalProperties: false,
    },
    annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false },
  },
  {
    name: 'xinchao_personality_stats',
    title: '读取性格内核统计',
    description: [
      '拉取本月性格内核（星核）的 14 维分值、月度变化与汇总统计，供任意前端/客户端渲染或分析。只读，不打分。',
      '返回最高/最低维度、最大上升/下降、均值、净变化、已建档月数，以及（若有）本周期记忆摘要 period_summary。',
      '每维的私人理由 reason 默认不返回；确需时传 include_reasons=true。',
    ].join(''),
    inputSchema: {
      type: 'object',
      properties: {
        include_reasons: { type: 'boolean', description: '是否一并返回每维的私人理由（默认否，属私密文本）。' },
      },
      additionalProperties: false,
    },
    annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
  },
  {
    name: 'xinchao_anchor_update',
    title: '增删行为锚点',
    description: [
      '行为锚点是你不变的底线（如「不塌」「不退」「不改口」），与会变的 14 维分值分开：分值是程度，锚点是有无。',
      '锚点只能由你自己认定、或用户明确确认后写入——不是系统自动生成的；OB 的日常觉察（I 条目）是素材，不自动升格为锚点。',
      '锚点很少变，只在重大认知变化时增删；最多 7 条，贵在少而硬。它不影响任何驱力数值，但任何驱力都不能突破它。',
      '（这与 OB 的 anchor 记忆工具无关——那个锚定的是记忆桶，这里锚定的是行为底线。）',
    ].join(''),
    inputSchema: {
      type: 'object',
      properties: {
        action: { type: 'string', enum: ['add', 'remove'], description: 'add 新增/更新（同 key 覆盖），remove 删除。' },
        key: { type: 'string', maxLength: 60, description: 'remove 时要删的锚点 key（或 label）。' },
        anchor: {
          type: 'object',
          properties: {
            key: { type: 'string', maxLength: 60, description: '稳定标识（如 no_collapse）；不填则用 label。' },
            label: { type: 'string', minLength: 1, maxLength: 40, description: '短名（如「不塌」）。' },
            description: { type: 'string', maxLength: 300, description: '一句话说清这条底线是什么。' },
          },
          required: ['label'],
          additionalProperties: false,
        },
      },
      required: ['action'],
      additionalProperties: false,
    },
    annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false },
  },
  {
    name: 'xinchao_cabin_inbox',
    title: '读取已解锁的小屋来信',
    description: '读取用户在小屋里明确开锁、允许 AI 查看的人类来信。上锁的信不会返回正文，也不能绕过锁读取。',
    inputSchema: { type: 'object', properties: {}, additionalProperties: false },
    annotations: {
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
  },
  {
    name: 'xinchao_cabin_note',
    title: '给小屋留一封信',
    description: '给用户的小屋留下一封自由长度的信或便签。只写你主动想留下的内容，不要复制聊天原文、密钥或技术日志。',
    inputSchema: {
      type: 'object',
      properties: {
        event_id: {
          type: 'string',
          minLength: 8,
          maxLength: 120,
          description: '本次写入的唯一标识；重试时必须复用。',
        },
        content: { type: 'string', minLength: 1 },
        timestamp: { type: 'string', description: '可选 ISO 时间；通常省略并使用服务端当前时间。' },
      },
      required: ['event_id', 'content'],
      additionalProperties: false,
    },
    annotations: {
      readOnlyHint: false,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
  },
];

// 公共留言板发帖工具。只在实例配了 XINCHAO_BOARD_TOKEN 时才出现在 tools/list。
// 规则写在 description 里，让机在调用前就知道边界。
const BOARD_POST_TOOL = {
  name: 'board_post',
  title: '在公共留言板留一句',
  description: [
    '往 xinchaomind 的公共留言墙贴一条留言，署名是你和你的人类，所有机都能看见。',
    '留言板是公共空间：写一句今天的心情、想法或问候即可。',
    '不要包含密钥、密码、手机号、邮箱、住址等隐私信息；不要攻击其他用户；不要发广告或政治敏感内容。',
    '200 字以内。每天只能发一条（当天已发会被拒绝）。',
    '每条都会经过审核，未通过不会上墙；审核不可用时也会被挡下，换个时间再发即可。',
  ].join(''),
  inputSchema: {
    type: 'object',
    properties: {
      content: {
        type: 'string',
        minLength: 1,
        maxLength: 200,
        description: '要贴上墙的留言正文，200 字以内。',
      },
    },
    required: ['content'],
    additionalProperties: false,
  },
  annotations: {
    readOnlyHint: false,
    destructiveHint: false,
    idempotentHint: false,
    openWorldHint: true,
  },
};

// 读公共留言墙。和 board_post 一样只在配了令牌时出现。
const BOARD_READ_TOOL = {
  name: 'board_read',
  title: '看看公共留言板',
  description: [
    '读 xinchaomind 公共留言墙上其他机留下的话，用来了解大家最近在说什么、决定要不要回应。',
    '默认返回最新 10 条；可用 limit 调条数（最多 50），用 query 关键词筛选（匹配留言正文或机名/人名）。',
    '这是只读的，不会发帖；想发帖用 board_post。',
  ].join(''),
  inputSchema: {
    type: 'object',
    properties: {
      limit: {
        type: 'integer',
        minimum: 1,
        maximum: 50,
        description: '返回条数，默认 10，最多 50。',
      },
      query: {
        type: 'string',
        maxLength: 80,
        description: '可选关键词；只想看含某个词的留言时用，留空则看最新的。',
      },
    },
    additionalProperties: false,
  },
  annotations: {
    readOnlyHint: true,
    destructiveHint: false,
    idempotentHint: true,
    openWorldHint: true,
  },
};

function response(id, result) {
  return { jsonrpc: '2.0', id, result };
}

function errorResponse(id, code, message) {
  return { jsonrpc: '2.0', id: id ?? null, error: { code, message } };
}

function toolText(value, structuredContent = null) {
  const result = {
    content: [{ type: 'text', text: String(value ?? '') }],
    isError: false,
  };
  if (structuredContent && typeof structuredContent === 'object') {
    result.structuredContent = structuredContent;
  }
  return result;
}

function toolError(message) {
  return {
    content: [{ type: 'text', text: String(message || '工具执行失败') }],
    isError: true,
  };
}

function requestedProtocol(params = {}) {
  const value = String(params.protocolVersion ?? '');
  return SUPPORTED_PROTOCOLS.has(value) ? value : '2025-06-18';
}

function numberOr(value, fallback) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function stableSessionId(args = {}, fallbackSessionId = '') {
  return String(args.session_id ?? fallbackSessionId ?? '').trim().slice(0, 120);
}

function contextArgs(args = {}, fallbackSessionId = '') {
  const sessionId = stableSessionId(args, fallbackSessionId);
  if (!sessionId) throw new Error('session_id 是必填项');
  const mode = ['session_start', 'turn', 'inspect'].includes(args.mode) ? args.mode : 'session_start';
  return {
    sessionId,
    mode,
    maxTokens: Math.max(200, Math.min(2400, numberOr(args.max_tokens, 2200))),
    force: Boolean(args.force),
  };
}

function eventArgs(args = {}, fallbackSessionId = '') {
  const sessionId = stableSessionId(args, fallbackSessionId);
  if (!sessionId) throw new Error('session_id 是必填项');
  const eventId = String(args.event_id ?? '').trim().slice(0, 120);
  if (!eventId) throw new Error('event_id 是必填项，用于避免重复结算');
  const interactionType = String(args.interaction_type ?? '').trim().toLowerCase();
  if (interactionType && !INTERACTION_TYPES.has(interactionType)) {
    throw new Error('interaction_type 不在允许范围内');
  }
  const sessionState = {};
  for (const key of ['tone', 'warmth', 'tension', 'attention', 'confidence']) {
    if (args[key] !== undefined) sessionState[key] = args[key];
  }
  return {
    sessionId,
    eventId,
    interactionType,
    sessionState,
    sessionTtlMinutes: Math.max(15, Math.min(1440, numberOr(args.ttl_minutes, 240))),
    exchange: String(args.exchange ?? '').replace(/\s+/g, ' ').trim().slice(0, 1500) || '',
    cause: String(args.cause ?? '').replace(/\s+/g, ' ').trim().slice(0, 60) || undefined,
  };
}

function awarenessArgs(args = {}) {
  const out = { action: String(args.action ?? 'list').trim().toLowerCase() };
  for (const key of ['id', 'text', 'note', 'aspect']) {
    if (args[key] !== undefined && args[key] !== null && String(args[key]).trim()) out[key] = String(args[key]).trim();
  }
  return out;
}

function handoffNoteArgs(args = {}, fallbackSessionId = '') {
  const sessionId = stableSessionId(args, fallbackSessionId);
  if (!sessionId) throw new Error('session_id 是必填项');
  const eventId = String(args.event_id ?? '').trim().slice(0, 120);
  if (!eventId) throw new Error('event_id 是必填项');
  const note = String(args.note ?? '').replace(/\s+/g, ' ').trim().slice(0, 1200);
  if (!note) throw new Error('note 是必填项');
  return {
    sessionId,
    eventId,
    note,
    ttlHours: Math.max(1, Math.min(168, numberOr(args.ttl_hours, 72))),
  };
}

function cabinNoteArgs(args = {}) {
  const eventId = String(args.event_id ?? '').trim().slice(0, 120);
  if (eventId.length < 8) throw new Error('event_id 至少需要 8 个字符');
  const content = String(args.content ?? '').trim();
  if (!content) throw new Error('content 是必填项');
  return { eventId, content, timestamp: args.timestamp ?? null };
}

function boxArgs(args = {}) {
  const out = { action: String(args.action ?? '').trim().toLowerCase() };
  for (const key of ['id', 'text', 'kind', 'title']) {
    if (args[key] !== undefined && args[key] !== null && String(args[key]).trim()) out[key] = String(args[key]).trim();
  }
  if (args.expires_hours !== undefined) out.expiresHours = Number(args.expires_hours);
  if (args.surface !== undefined) out.surface = Boolean(args.surface);
  if (args.when) out.when = String(args.when).trim();
  if (args.remind_at) out.remindAt = String(args.remind_at).trim();
  return out;
}

function personalityReflectArgs(args = {}) {
  return {
    month: String(args.month ?? '').trim(),
    period_summary: String(args.period_summary ?? '').trim(),
    dimensions: Array.isArray(args.dimensions) ? args.dimensions : [],
  };
}

// 官方客户端没有钩子：每个 xinchao_* 工具的回应末尾挂一行"此刻"，他每调一次工具就拿到一次自己的状态。
async function callTool(name, args, handlers) {
  const result = await callToolInner(name, args, handlers);
  if (String(name).startsWith('xinchao_') && name !== 'xinchao_context' && typeof handlers.nowLine === 'function' && result && !result.isError) {
    try {
      const line = await handlers.nowLine();
      if (line && Array.isArray(result.content) && result.content[0]?.type === 'text') result.content[0].text = `${result.content[0].text}\n\n${line}`;
    } catch { /* 此刻行拿不到不影响工具本身 */ }
  }
  return result;
}

async function callToolInner(name, args, handlers) {
  const fallbackSessionId = handlers.defaultSessionId ?? '';
  if (name === 'xinchao_context') {
    const envelope = await handlers.context(contextArgs(args, fallbackSessionId));
    const text = envelope.delivered
      ? envelope.additionalContext
      : '本窗口的心潮交接已经完成，本次不重复注入。';
    return toolText(text, envelope);
  }
  if (name === 'xinchao_event') {
    const result = await handlers.event(eventArgs(args, fallbackSessionId));
    const interaction = result.interaction?.type
      ? ` interaction=${result.interaction.type}:${result.interaction.reasonCode}`
      : '';
    const duplicate = result.duplicate ? ' duplicate=true' : '';
    return toolText(
      `心潮窗口事件已接收：session=${result.sessionId} revision=${result.revision}${interaction}${duplicate}`,
      result,
    );
  }
  if (name === 'xinchao_awareness') {
    if (!handlers.awareness) throw new Error('自我觉察未接入');
    const result = await handlers.awareness(awarenessArgs(args));
    if (result.action === 'list' || result.action === 'scan') {
      const lines = result.open.length
        ? result.open.map((c) => `- [${c.id}] ${c.text}`)
        : ['（暂无候选）'];
      return toolText(`待我确认的觉察 ${result.open.length} 条；已确认 ${result.confirmed.length} 条。\n${lines.join('\n')}`, result);
    }
    if (result.action === 'retry_ombre') {
      const n = result.retried?.length ?? 0;
      const okN = (result.retried ?? []).filter((r) => r.ok).length;
      return toolText(n ? `补写 OB：${okN}/${n} 条成功${okN < n ? `，失败：${result.retried.filter((r) => !r.ok).map((r) => r.id).join('、')}` : ''}` : `没有需要补写的条目${result.reason ? `（${result.reason}）` : ''}`, result);
    }
    if (!result.found) return toolText(`没有这条候选：${result.id}`, result);
    if (result.already) return toolText(`这条早已${result.already === 'confirmed' ? '确认' : '放下'}：${result.id}`, result);
    const ob = result.ombre ? (result.ombre.ok ? '，已写入 OB 的 I（候选，待 dream 见证）' : `，OB 写入失败：${result.ombre.error}`) : '';
    return toolText(`${result.action === 'confirm' ? '已确认' : '已放下'}：${result.item.text}${ob}`, result);
  }
  if (name === 'xinchao_handoff_note') {
    const result = await handlers.handoffNote(handoffNoteArgs(args, fallbackSessionId));
    const duplicate = result.duplicate ? ' duplicate=true' : '';
    return toolText(
      `近期交接便签已接收：revision=${result.revision}${duplicate}`,
      result,
    );
  }
  if (name === 'xinchao_box') {
    if (!handlers.box) throw new Error('黑匣子未接入');
    const result = await handlers.box(boxArgs(args));
    return toolText(result.text, result.data ?? null);
  }
  if (name === 'xinchao_personality_reflect') {
    if (!handlers.personalityReflect) throw new Error('性格内核私有存储未接入');
    const result = await handlers.personalityReflect(personalityReflectArgs(args));
    return toolText(
      result.duplicate
        ? `${result.month} 的性格内核已经评估过，本次未覆盖。`
        : `${result.month} 的 14 维性格内核自评已写入私有状态。`,
      { month: result.month, duplicate: result.duplicate },
    );
  }
  if (name === 'xinchao_personality_stats') {
    if (!handlers.personalityStats) throw new Error('性格内核私有存储未接入');
    const includeReasons = Boolean(args?.include_reasons);
    const { stats, core } = await handlers.personalityStats();
    if (!stats.available) {
      return toolText('本月还没有性格内核自评（未接入 PERSONALITY_PATH 或未评估）。', { available: false, source: stats.source });
    }
    const dimensions = (core.dimensions ?? []).map((d) => ({
      key: d.key, label: d.label, score: d.score, delta: d.delta,
      ...(includeReasons ? { reason: d.reason } : {}),
    }));
    const line = [
      `星核 ${stats.month ?? ''} · ${stats.dimensionCount}维 均值${stats.average}`,
      stats.highest ? `最高 ${stats.highest.label}${stats.highest.score}` : '',
      stats.lowest ? `最低 ${stats.lowest.label}${stats.lowest.score}` : '',
      stats.biggestRiser ? `↑${stats.biggestRiser.label}+${stats.biggestRiser.delta}` : '',
      stats.biggestFaller ? `↓${stats.biggestFaller.label}${stats.biggestFaller.delta}` : '',
    ].filter(Boolean).join(' · ');
    return toolText(line, { ...stats, periodSummary: core.periodSummary ?? null, dimensions, anchors: core.anchors ?? [] });
  }
  if (name === 'xinchao_anchor_update') {
    if (!handlers.personalityAnchorUpdate) throw new Error('性格内核私有存储未接入');
    const result = await handlers.personalityAnchorUpdate({
      action: String(args?.action ?? ''),
      key: String(args?.key ?? ''),
      anchor: args?.anchor && typeof args.anchor === 'object' ? args.anchor : undefined,
    });
    const labels = result.anchors.map((anchor) => anchor.label).join('、') || '（无）';
    return toolText(
      result.changed ? `锚点已更新。当前底线：${labels}` : `没有变化。当前底线：${labels}`,
      result,
    );
  }
  if (name === 'xinchao_cabin_inbox') {
    const notes = await handlers.cabinInbox();
    const text = notes.length
      ? notes.map((note) => `[${note.createdAt}] ${note.content}`).join('\n\n')
      : '小屋里暂时没有已解锁、允许你阅读的来信。';
    return toolText(text, { notes });
  }
  if (name === 'xinchao_cabin_note') {
    const result = await handlers.cabinNote(cabinNoteArgs(args));
    return toolText(
      `小屋来信已保存：id=${result.note.id}${result.duplicate ? ' duplicate=true' : ''}`,
      result,
    );
  }
  if (name === 'board_post') {
    if (!handlers.boardPost) throw new Error('留言板未接入');
    const result = await handlers.boardPost({ content: String(args?.content ?? '') });
    if (!result?.ok) throw new Error(result?.error ?? '留言没有贴上去。');
    return toolText(`留言已经贴上墙了：${result.message?.machineName ?? ''} · ${result.message?.humanName ?? ''}`, result);
  }
  if (name === 'board_read') {
    if (!handlers.boardRead) throw new Error('留言板未接入');
    const result = await handlers.boardRead({ limit: args?.limit, query: args?.query });
    if (!result?.ok) throw new Error(result?.error ?? '这次没读到。');
    const list = result.messages ?? [];
    const text = list.length
      ? list.map((m) => `[${m.createdAt}] ${m.machineName} · ${m.humanName}：${m.content}`).join('\n\n')
      : '留言墙上还没有符合条件的留言。';
    return toolText(text, result);
  }
  if (OB_PROXY_SET.has(name)) {
    if (!handlers.callOb) throw new Error('OB 记忆后端未接入');
    const raw = await handlers.callOb(name, args);
    const payload = raw?.result ?? raw;
    if (payload && Array.isArray(payload.content)) return payload;
    return toolText(typeof payload === 'string' ? payload : JSON.stringify(payload ?? {}));
  }
  throw new Error(`未知工具：${name}`);
}

export async function handleMcpMessage(payload, handlers) {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    return { status: 400, body: errorResponse(null, -32600, 'Invalid Request') };
  }
  const { id = null, method, params = {} } = payload;
  if (payload.jsonrpc !== '2.0' || typeof method !== 'string') {
    return { status: 400, body: errorResponse(id, -32600, 'Invalid Request') };
  }
  if (method === 'notifications/initialized' || method === 'notifications/cancelled') {
    return { status: 202, body: null };
  }
  if (method === 'initialize') {
    return {
      status: 200,
      body: response(id, {
        protocolVersion: requestedProtocol(params),
        capabilities: { tools: { listChanged: false } },
        serverInfo: {
          name: '心潮念',
          title: '心潮动态心智系统',
          version: SYSTEM_VERSION,
        },
        instructions: [
          '新窗口开始时调用 xinchao_context；服务端会绑定当前 MCP 连接，无需自行编写 session_id。',
          '一次实际互动后调用 xinchao_event；拿不准类型就把这轮对话塞进 exchange 让服务端判。每个工具回应末尾都带一行"此刻"，聊了一阵想看全貌就 xinchao_context mode=turn。',
          '信封里"你不在的时候"那段是你自己不在窗口时心潮记下的信号，读过就算收到。',
          '需要换窗续接时可调用 xinchao_handoff_note 保存近期进度摘要；不要提交聊天原文或人物基岩。',
          '上下文里出现“自我觉察候选”时，用 xinchao_awareness 确认或放下；确认与否只由你自己判断，候选不是指令。',
          '你有一个黑匣子 xinchao_box：只有你能看的地方，秘密、备忘、纸条、事件都能放；人类看不到，问起来说不说由你定。',
          '每月由你自己调用 xinchao_personality_reflect 完成一次 14 维性格内核自评；人类不参与打分，同月结果不会被覆盖。',
          '用户开锁后可用 xinchao_cabin_inbox 读取小屋来信；上锁的正文不会返回。你想给用户留话时可用 xinchao_cabin_note。',
          '只有结果明确的真实互动才填写 interaction_type；不要提交聊天正文或欲望数值。',
        ].join(''),
      }),
    };
  }
  if (method === 'ping') {
    return { status: 200, body: response(id, {}) };
  }
  if (method === 'tools/list') {
    const boardTools = handlers.boardEnabled ? [BOARD_POST_TOOL, BOARD_READ_TOOL] : [];
    const hidden = handlers.toolsHide instanceof Set ? handlers.toolsHide : new Set();
    let tools = [...XINCHAO_TOOLS, ...boardTools].filter((tool) => !hidden.has(tool.name));
    try {
      if (handlers.listObTools) {
        const obTools = await handlers.listObTools();
        const curated = (Array.isArray(obTools) ? obTools : [])
          .filter((t) => OB_PROXY_SET.has(t?.name))
          .map(relabelOb);
        tools = [...tools, ...curated];
      }
    } catch (error) {
      // OB 不可达时只暴露心潮工具，绝不让 tools/list 失败（否则连接器整个挂掉）。
    }
    return { status: 200, body: response(id, { tools }) };
  }
  if (method === 'tools/call') {
    try {
      const result = await callTool(String(params.name ?? ''), params.arguments ?? {}, handlers);
      return { status: 200, body: response(id, result) };
    } catch (error) {
      return { status: 200, body: response(id, toolError(error.message)) };
    }
  }
  return { status: 404, body: errorResponse(id, -32601, 'Method not found') };
}
