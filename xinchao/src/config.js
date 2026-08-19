function bool(name, fallback = false) {
  const raw = process.env[name];
  return raw == null ? fallback : ['1', 'true', 'yes', 'on'].includes(raw.toLowerCase());
}

function number(name, fallback, min, max) {
  const parsed = Number(process.env[name] ?? fallback);
  if (!Number.isFinite(parsed)) throw new Error(`${name} must be numeric`);
  return Math.max(min, Math.min(max, parsed));
}

export function loadConfig() {
  const agentName = process.env.AGENT_NAME ?? 'AI 助手';
  // 默认值会直接出现在推送和桥消息里被本人读到，所以不用「用户」这种后台称呼。
  // 自己部署的人应该设成对方真正的名字，这只是没设时的兜底。
  const notificationRecipient = process.env.NOTIFICATION_RECIPIENT ?? '你的人类';
  return {
    identity: { agentName, notificationRecipient },
    port: number('PORT', 18110, 1, 65535),
    serviceToken: process.env.SERVICE_TOKEN ?? '',
    statePath: process.env.STATE_PATH ?? '/app/state/state.json',
    personalityPath: process.env.PERSONALITY_PATH ?? '/app/state/personality.json',
    personality: {
      // Optional presentation metadata only. Scores and reasons still come
      // exclusively from the deployment-side, read-only personality mirror.
      zodiac: String(process.env.PERSONALITY_ZODIAC ?? '').trim() || null,
    },
    journalPath: process.env.TRANSITION_JOURNAL_PATH ?? '/app/state/transitions.jsonl',
    settleIntervalMinutes: number('SETTLE_INTERVAL_MINUTES', 15, 1, 1440),
    sleepAfterMinutes: number('SLEEP_AFTER_MINUTES', 90, 5, 10080),
    shadowMode: bool('SHADOW_MODE', true),
    model: {
      enabled: bool('MODEL_ENABLED', false),
      baseUrl: (process.env.MODEL_BASE_URL ?? 'http://127.0.0.1:11434/v1').replace(/\/$/, ''),
      apiKey: process.env.MODEL_API_KEY ?? '',
      name: process.env.MODEL_NAME ?? 'local-model',
      timeoutMs: number('MODEL_TIMEOUT_MS', 30000, 1000, 120000),
      maxInputChars: number('MODEL_MAX_INPUT_CHARS', 10000, 1000, 50000),
      maxOutputTokens: number('MODEL_MAX_OUTPUT_TOKENS', 650, 100, 4000),
      dreamPushPromptPath: process.env.DREAM_PUSH_PROMPT_PATH ?? '/app/configs/dream_push_prompt.md',
      agentName,
      notificationRecipient,
    },
    dreamMinIntervalHours: number('DREAM_MIN_INTERVAL_HOURS', 6, 1, 168),
    dreamMaxPerDay: number('DREAM_MAX_PER_DAY', 4, 1, 12),
    dreamEnabled: bool('DREAM_ENABLED', true),
    ombre: {
      url: process.env.OMBRE_MCP_URL ?? '',
      token: process.env.OMBRE_MCP_TOKEN ?? '',
      readEnabled: bool('OMBRE_READ_ENABLED', false),
      writeEnabled: bool('OMBRE_WRITE_ENABLED', false),
      breathMaxResults: number('OMBRE_BREATH_MAX_RESULTS', 3, 1, 10),
      breathMaxTokens: number('OMBRE_BREATH_MAX_TOKENS', 800, 200, 3000)
    },
    context: {
      enabled: bool('CONTEXT_ENVELOPE_ENABLED', true),
      ombreEnabled: bool('CONTEXT_OMBRE_ENABLED', false),
      // This budget only carries short-lived state and recent continuity.
      // Stable identity/core instructions are loaded separately by the client
      // and must never be squeezed into this short-lived envelope.
      defaultMaxTokens: number('CONTEXT_DEFAULT_MAX_TOKENS', 2200, 200, 4000),
      ombreMaxTokens: number('CONTEXT_OMBRE_MAX_TOKENS', 1600, 200, 3000),
      ttlMinutes: number('CONTEXT_TTL_MINUTES', 15, 1, 180),
      handoffOnceHours: number('CONTEXT_HANDOFF_ONCE_HOURS', 12, 1, 168),
    },
    mcp: {
      enabled: bool('MCP_ENABLED', false),
      pathToken: process.env.MCP_PATH_TOKEN ?? '',
    },
    oauth: {
      enabled: bool('OAUTH_ENABLED', false),
      publicBaseUrl: (process.env.OAUTH_PUBLIC_BASE_URL ?? '').replace(/\/$/, ''),
      approvalToken: process.env.OAUTH_APPROVAL_TOKEN ?? '',
      statePath: process.env.OAUTH_STATE_PATH ?? '/app/state/oauth.json',
      accessTtlSeconds: number('OAUTH_ACCESS_TTL_SECONDS', 86400, 300, 2592000),
      refreshTtlSeconds: number('OAUTH_REFRESH_TTL_SECONDS', 31536000, 86400, 63072000),
    },
    dashboard: {
      enabled: bool('DASHBOARD_ENABLED', false),
      publicBaseUrl: (process.env.DASHBOARD_PUBLIC_BASE_URL ?? process.env.OAUTH_PUBLIC_BASE_URL ?? '').replace(/\/$/, ''),
      accessToken: process.env.DASHBOARD_ACCESS_TOKEN ?? '',
      sessionTtlSeconds: number('DASHBOARD_SESSION_TTL_SECONDS', 43200, 900, 604800),
      includePrivateText: bool('DASHBOARD_INCLUDE_PRIVATE_TEXT', false),
      dreamLimit: number('DASHBOARD_DREAM_LIMIT', 12, 1, 30),
      // 允许指定网页从浏览器直接读取这台心潮。默认空 = 不允许跨源请求。
      // 多个完整来源用逗号分隔，末尾斜杠会自动归一化。
      allowedOrigins: String(process.env.DASHBOARD_ALLOWED_ORIGINS ?? '')
        .split(',').map((value) => value.trim().replace(/\/$/, '')).filter(Boolean),
    },
    interaction: {
      maxEffectsPerDay: number('INTERACTION_MAX_EFFECTS_PER_DAY', 24, 1, 96),
      timeZone: process.env.INTERACTION_TIME_ZONE ?? process.env.SETTLE_TIME_ZONE ?? 'Asia/Shanghai',
    },
    bridge: {
      enabled: bool('BRIDGE_ENABLED', false),
      machineToken: process.env.BRIDGE_MACHINE_TOKEN ?? '',
      statePath: process.env.BRIDGE_STATE_PATH ?? '/app/state/bridge-queue.json',
      maxEntries: number('BRIDGE_MAX_ENTRIES', 500, 10, 5000),
      ttlHours: number('BRIDGE_TTL_HOURS', 168, 1, 720),
      pollSeconds: number('BRIDGE_POLL_SECONDS', 15, 2, 300),
    },
    cabin: {
      statePath: process.env.CABIN_STATE_PATH ?? '/app/state/cabin.json',
      maxNotes: number('CABIN_MAX_NOTES', 2000, 10, 10000),
      maxLedgerEntries: number('CABIN_MAX_LEDGER_ENTRIES', 5000, 10, 20000),
    },
    heartbeat: {
      filePath: process.env.OMBRE_HEARTBEAT_FILE ?? '/memory-data/heartbeat.json',
      // Dream residue may be shared after a shorter quiet period. Autonomous
      // contact stays on the stricter, long-absence threshold below.
      dreamMinIdleHours: number('BARK_DREAM_MIN_CONTACT_IDLE_HOURS', 3, 1, 24),
      proactiveMinIdleHours: number('BARK_MIN_CONTACT_IDLE_HOURS', 12, 1, 720)
    },
    bark: {
      enabled: bool('BARK_ENABLED', false),
      key: process.env.BARK_KEY ?? '',
      server: (process.env.BARK_SERVER ?? 'https://api.day.app').replace(/\/$/, ''),
      title: process.env.BARK_TITLE ?? agentName,
      group: process.env.BARK_GROUP ?? 'xinchao',
      icon: process.env.BARK_ICON ?? '',
      sound: process.env.BARK_SOUND ?? 'silence',
      level: process.env.BARK_LEVEL ?? 'timeSensitive',
      minIntervalHours: number('BARK_MIN_INTERVAL_HOURS', 3, 1, 168),
      autonomousMinIntervalHours: number('BARK_AUTONOMOUS_MIN_INTERVAL_HOURS', 12, 1, 720),
      maxPerDay: number('BARK_MAX_PER_DAY', 6, 1, 24),
      minDrive: number('BARK_MIN_DRIVE', 0.42, 0.05, 1)
    },
    settle: {
      timeZone: process.env.SETTLE_TIME_ZONE ?? process.env.DAYTIME_TIME_ZONE ?? 'Asia/Shanghai',
      dawnFreezeStart: number('DAWN_FREEZE_START', 1, 0, 12),
      dawnFreezeEnd: number('DAWN_FREEZE_END', 8, 1, 12),
      // SATIETY_HOURS 是 3.1 公开名称；开发期旧名仅作兼容回退。
      satisfactionPlateauHours: process.env.SATIETY_HOURS !== undefined
        ? number('SATIETY_HOURS', 2, 0, 24)
        : number('SATISFACTION_PLATEAU_HOURS', 2, 0, 24),
      couplingEnabled: bool('DRIVE_COUPLING_ENABLED', true),
    },
    daytime: {
      enabled: bool('DAYTIME_EMERGENCE_ENABLED', false),
      timeZone: process.env.DAYTIME_TIME_ZONE ?? 'Asia/Shanghai',
      startHour: number('DAYTIME_START_HOUR', 8, 0, 23),
      endHour: number('DAYTIME_END_HOUR', 23, 1, 24),
      minIntervalHours: number('DAYTIME_MIN_INTERVAL_HOURS', 2, 0.25, 24),
      maxIntervalHours: number('DAYTIME_MAX_INTERVAL_HOURS', 3, 0.25, 24),
      maxPerDay: number('DAYTIME_MAX_PER_DAY', 7, 1, 24)
    },
    // 输出回流：他说出口的自主表达回过头在思维池里留痕。默认开——闭环的第一块。
    reflux: {
      enabled: bool('OUTPUT_REFLUX_ENABLED', true),
      amount: number('OUTPUT_REFLUX_AMOUNT', 0.30, 0.05, 0.6)
    },
    // 记忆共振：浮现的记忆按 domain→亲和度回推微调驱力（"想起什么"影响"想要什么"）。
    resonance: {
      enabled: bool('MEMORY_RESONANCE_ENABLED', true),
      nudge: number('MEMORY_RESONANCE_NUDGE', 0.02, 0.005, 0.1),
      perCallCap: number('MEMORY_RESONANCE_PER_CALL_CAP', 0.06, 0.01, 0.3)
    },
    // 作息预期：从她真实到达的节律学习，临近她常来的时段生出"在等你"的期待感（只表达守候，不责备）。
    anticipation: {
      enabled: bool('ANTICIPATION_ENABLED', true),
      arrivalGapMinutes: number('ANTICIPATION_ARRIVAL_GAP_MINUTES', 90, 15, 720)
    },
    // 挂念：作息预期的另一半。她过了常来的点还没来 → 轻推 monitor(惦记)，硬顶在 3A 天花板内、
    // 不自激；只在她活跃时段念，静默时段(在睡)不念。失落内化，绝不责备。
    longing: {
      enabled: bool('LONGING_ENABLED', true),
      nudge: number('LONGING_NUDGE', 0.02, 0.005, 0.1),
      cap: number('LONGING_CAP', 0.04, 0.01, 0.2),
      onsetHours: number('LONGING_ONSET_HOURS', 6, 1, 48),
      fullHours: number('LONGING_FULL_HOURS', 18, 2, 96)
    },
    // 公共留言板：机经 board_post 工具往 xinchaomind 的公共留言墙发帖。
    // token 是这台机在平台上的身份凭证（网页里「取留言板令牌」拿到），没填就没这工具。
    board: {
      endpoint: (process.env.XINCHAO_BOARD_ENDPOINT ?? 'https://xinchaomind.uk/api/board/ingest').replace(/\/+$/, ''),
      token: process.env.XINCHAO_BOARD_TOKEN ?? ''
    }
  };
}

export function validateConfig(config) {
  // 常见踩坑：配了 OB 地址却没打开 read —— OB 明明部署好了，网页端（xinchaomind.uk）
  // 却一直显示"未接入 OB / 记忆星图不可用"。这不是报错（标准部署可以没有 OB），
  // 但配了地址却没开 read 几乎一定是漏配，所以在这里明确告警，省得反复排查。
  if (String(config.ombre.url || '').trim() && !config.ombre.readEnabled) {
    console.warn(
      '[xinchao] OMBRE_MCP_URL 已配置，但 OMBRE_READ_ENABLED=false —— '
      + '网页端会显示"未接入 OB"，即使 OB 已正确部署也一样。'
      + '要在网页端看记忆星图/接入 OB，请把 OMBRE_READ_ENABLED 设为 true 后重启容器。'
    );
  }

  const externalMemoryEnabled = Boolean(
    config.ombre.readEnabled
    || config.ombre.writeEnabled
    || config.context.ombreEnabled
  );
  if (externalMemoryEnabled) {
    if (!String(config.ombre.url || '').trim()) {
      throw new Error(
        'OMBRE_MCP_URL is required when external memory integration is enabled'
      );
    }
    if (!String(config.ombre.token || '').trim()) {
      throw new Error(
        'OMBRE_MCP_TOKEN is required when external memory integration is enabled'
      );
    }
  }
  if (config.dashboard?.enabled) {
    const accessToken = String(config.dashboard.accessToken || '');
    if (accessToken.length < 32) {
      throw new Error('DASHBOARD_ACCESS_TOKEN must contain at least 32 characters when Dashboard is enabled');
    }
    if (accessToken === String(config.serviceToken || '')) {
      throw new Error('DASHBOARD_ACCESS_TOKEN must be different from SERVICE_TOKEN');
    }
    const publicBaseUrl = String(config.dashboard.publicBaseUrl || '');
    if (!publicBaseUrl) {
      throw new Error('DASHBOARD_PUBLIC_BASE_URL is required when Dashboard is enabled');
    }
    let parsed;
    try { parsed = new URL(publicBaseUrl); }
    catch { throw new Error('DASHBOARD_PUBLIC_BASE_URL must be a valid URL'); }
    const local = ['localhost', '127.0.0.1', '::1'].includes(parsed.hostname);
    if (parsed.protocol !== 'https:' && !(local && parsed.protocol === 'http:')) {
      throw new Error('DASHBOARD_PUBLIC_BASE_URL must use HTTPS outside localhost');
    }
  }
  if (config.bridge?.enabled) {
    const token = String(config.bridge.machineToken || '');
    if (token.length < 32) throw new Error('BRIDGE_MACHINE_TOKEN must contain at least 32 characters when Bridge is enabled');
    if ([config.serviceToken, config.dashboard?.accessToken].filter(Boolean).includes(token)) {
      throw new Error('BRIDGE_MACHINE_TOKEN must be independent from service and dashboard tokens');
    }
  }
  return config;
}
