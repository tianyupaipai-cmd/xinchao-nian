import { DIMENSIONS, DRIVE_KEYS } from './dimensions.js';

const clamp = (value, min = 0, max = 1) => Math.max(min, Math.min(max, Number(value) || 0));

function compact(value, maxLength = 280) {
  return String(value ?? '').replace(/\s+/g, ' ').trim().slice(0, maxLength);
}

function validDate(value) {
  const timestamp = Date.parse(value ?? '');
  return Number.isFinite(timestamp) ? new Date(timestamp).toISOString() : null;
}

function driveLevel(value) {
  if (value >= 0.75) return 'surging';
  if (value >= 0.5) return 'rising';
  if (value >= 0.25) return 'present';
  return 'quiet';
}

function projectedDrives(state) {
  return DRIVE_KEYS.map((key) => {
    const value = Number(clamp(state?.drives?.[key]).toFixed(4));
    return {
      key,
      label: DIMENSIONS[key].label,
      value,
      percent: Math.round(value * 100),
      level: driveLevel(value),
    };
  });
}

function projectedThoughts(state) {
  const flash = Array.isArray(state?.thoughtPool?.flash) ? state.thoughtPool.flash : [];
  const obsessions = Array.isArray(state?.thoughtPool?.obsessions) ? state.thoughtPool.obsessions : [];
  const signals = [...flash, ...obsessions].reduce((result, item) => {
    if (!DRIVE_KEYS.includes(item?.key)) return result;
    result[item.key] = Math.max(result[item.key] ?? 0, clamp(item.intensity));
    return result;
  }, {});
  return {
    flashCount: flash.length,
    obsessionCount: obsessions.length,
    signals: Object.entries(signals).map(([key, intensity]) => ({
      key,
      intensity: Number(intensity.toFixed(4)),
    })),
  };
}

function projectedDreams(state, includePrivateText, limit = 12) {
  const dreams = Array.isArray(state?.recentDreams) ? state.recentDreams : [];
  return dreams.slice(-Math.max(1, Math.min(30, Number(limit) || 12))).reverse().map((dream) => {
    const summary = compact(dream?.summary || dream?.awareness, 360) || null;
    const lucidityNumber = Number(dream?.lucidity);
    const lucidity = dream?.lucidity != null && Number.isFinite(lucidityNumber)
      ? Number(clamp(lucidityNumber).toFixed(4))
      : null;
    return {
      id: compact(dream?.id, 120) || null,
      createdAt: validDate(dream?.createdAt),
      source: compact(dream?.source, 60) || 'unknown',
      hasDream: Boolean(compact(dream?.dream)),
      hasResidue: Boolean(compact(dream?.residue)),
      hasSummary: Boolean(summary),
      hasAwareness: Boolean(compact(dream?.awareness)),
      lucidity,
      ...(includePrivateText ? {
        dream: compact(dream?.dream, 4000) || null,
        summary,
        residue: compact(dream?.residue, 1200) || null,
        awareness: compact(dream?.awareness, 1200) || null,
      } : {}),
    };
  });
}

function activeSessionCount(state, now) {
  return Object.values(state?.sessionOverlays ?? {}).filter((session) => {
    const expiresAt = Date.parse(session?.expiresAt ?? '');
    return !Number.isFinite(expiresAt) || expiresAt > now.getTime();
  }).length;
}

export function buildDashboardSnapshot(state = {}, config = {}, now = new Date()) {
  const generatedAt = new Date(now);
  const drives = projectedDrives(state);
  const lastPresenceAt = validDate(state.lastHeartbeatAt ?? state.lastConversationAt);
  const lastPresenceMs = Date.parse(lastPresenceAt ?? '');
  const idleMinutes = Number.isFinite(lastPresenceMs)
    ? Math.max(0, Math.floor((generatedAt.getTime() - lastPresenceMs) / 60_000))
    : null;
  const topDrives = [...drives]
    .sort((left, right) => right.value - left.value)
    .slice(0, 4);

  return {
    schemaVersion: 1,
    system: 'xinchao-dynamic-mind',
    generatedAt: generatedAt.toISOString(),
    revision: Number(state.revision ?? 0),
    identity: {
      agentName: compact(config.identity?.agentName, 80) || '心潮',
      recipient: compact(config.identity?.notificationRecipient, 80) || '你的人类',
    },
    runtime: {
      mode: config.shadowMode ? 'shadow' : 'active',
      consciousness: compact(state.consciousness, 30) || 'unknown',
      fatigue: Number(clamp(state.fatigue, 0, 0.3).toFixed(4)),
      lastConversationAt: validDate(state.lastConversationAt),
      lastHeartbeatAt: validDate(state.lastHeartbeatAt),
      lastSettledAt: validDate(state.lastSettledAt),
      idleMinutes,
      activeSessions: activeSessionCount(state, generatedAt),
    },
    drives,
    topDrives,
    thoughts: projectedThoughts(state),
    dreams: projectedDreams(
      state,
      Boolean(config.dashboard?.includePrivateText),
      config.dashboard?.dreamLimit,
    ),
    deliveries: {
      recentNotifications: Array.isArray(state.recentBarkMessages) ? state.recentBarkMessages.length : 0,
      pendingAwareness: Boolean(state.pendingAwareness),
      nextDaytimeEmergenceAt: validDate(state.nextDaytimeEmergenceAt),
    },
    capabilities: {
      contextEnvelope: Boolean(config.context?.enabled),
      remoteMcp: Boolean(config.mcp?.enabled),
      oauth: Boolean(config.oauth?.enabled),
      externalMemoryRead: Boolean(config.ombre?.readEnabled),
      externalMemoryWrite: Boolean(config.ombre?.writeEnabled),
      notifications: Boolean(config.bark?.enabled),
      wakeBridgeProtocol: Boolean(config.bridge?.enabled),
      privateDreamText: Boolean(config.dashboard?.includePrivateText),
    },
  };
}

export function buildConnectionManifest(config = {}) {
  const dashboardBaseUrl = String(config.dashboard?.publicBaseUrl || config.oauth?.publicBaseUrl || '').replace(/\/$/, '');
  const mcpBaseUrl = String(config.oauth?.publicBaseUrl || config.dashboard?.publicBaseUrl || '').replace(/\/$/, '');
  return {
    schemaVersion: 1,
    system: 'xinchao-dynamic-mind',
    publicBaseUrl: dashboardBaseUrl || mcpBaseUrl || null,
    profiles: [
      {
        id: 'web-dashboard',
        audience: ['desktop-browser', 'mobile-browser', 'self-hosted-frontend'],
        enabled: Boolean(config.dashboard?.enabled),
        auth: 'http-only-session-cookie',
        endpoint: dashboardBaseUrl ? `${dashboardBaseUrl}/dashboard/session` : '/dashboard/session',
        note: '网页只提交一次 Dashboard 访问口令；服务密钥不会进入浏览器。',
      },
      {
        id: 'remote-mcp-oauth',
        audience: ['claude', 'chatgpt', 'gemini', 'oauth-capable-ai'],
        enabled: Boolean(config.mcp?.enabled && config.oauth?.enabled),
        auth: 'oauth-2.1-pkce',
        endpoint: mcpBaseUrl ? `${mcpBaseUrl}/mcp` : '/mcp',
        note: '优先用于支持远程 MCP 与 OAuth 的网页 AI。',
      },
      {
        id: 'remote-mcp-bearer',
        audience: ['claude-code', 'codex', 'ide', 'agent-runtime'],
        enabled: Boolean(config.mcp?.enabled),
        auth: 'bearer-token',
        endpoint: mcpBaseUrl ? `${mcpBaseUrl}/mcp` : '/mcp',
        note: 'Bearer 仅放在本地配置或服务器环境变量中。',
      },
      {
        id: 'http-api',
        audience: ['backend', 'cli', 'custom-integration'],
        enabled: true,
        auth: 'bearer-token',
        endpoint: dashboardBaseUrl ? `${dashboardBaseUrl}/v1` : '/v1',
        note: '适合后端代理和自动化；不应由浏览器直接保存 SERVICE_TOKEN。',
      },
      {
        id: 'runtime-bridge',
        audience: ['self-hosted-runtime', 'local-agent', 'custom-frontend-backend'],
        enabled: Boolean(config.bridge?.enabled),
        auth: 'dedicated-machine-bearer',
        endpoint: dashboardBaseUrl ? `${dashboardBaseUrl}/bridge/v1` : '/bridge/v1',
        note: '仅投递用户互动、便签和预约；机器 Token 只保存在 Bridge 本地环境。',
      },
    ],
    heartbeatProfiles: [
      { id: 'realtime', audience: 'large-context-agent', recommendation: 'message-hook' },
      { id: 'balanced', audience: 'standard-context-agent', recommendation: 'throttled-hook-or-breath' },
      { id: 'compat', audience: 'frontend-without-hooks', recommendation: 'breath-or-manual' },
    ],
    secrets: {
      included: false,
      note: '此清单永不返回 SERVICE_TOKEN、OAuth 令牌、Dashboard 访问口令或 Bridge 机器 Token。',
    },
  };
}
