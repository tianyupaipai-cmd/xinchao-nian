function cleanBaseUrl(value) {
  return String(value ?? '').trim().replace(/\/+$/, '');
}

export function memoryConnectionState(config = {}) {
  const urlConfigured = Boolean(String(config.ombre?.url ?? '').trim());
  const tokenConfigured = Boolean(String(config.ombre?.token ?? '').trim());
  const readEnabled = Boolean(config.ombre?.readEnabled);
  if (!urlConfigured) return 'ob_url_missing';
  if (!readEnabled) return 'ob_read_disabled';
  if (!tokenConfigured) return 'ob_token_missing';
  return 'ob_configured';
}

export function buildConnectionDiagnostics(config = {}) {
  const dashboardBaseUrl = cleanBaseUrl(config.dashboard?.publicBaseUrl);
  const mcpBaseUrl = cleanBaseUrl(config.oauth?.publicBaseUrl);
  const dashboardEnabled = Boolean(config.dashboard?.enabled);
  const mcpEnabled = Boolean(config.mcp?.enabled);
  const oauthEnabled = Boolean(config.oauth?.enabled);

  let dashboardState = 'dashboard_disabled';
  if (dashboardEnabled) dashboardState = dashboardBaseUrl ? 'dashboard_configured' : 'dashboard_base_url_missing';

  let mcpState = 'mcp_disabled';
  if (mcpEnabled && !oauthEnabled) mcpState = 'mcp_oauth_disabled';
  if (mcpEnabled && oauthEnabled) mcpState = mcpBaseUrl ? 'mcp_configured' : 'mcp_base_url_missing';

  return {
    schemaVersion: 1,
    publicVisualizer: {
      kind: 'public-web-app',
      url: 'https://xinchaomind.uk',
      acceptsMcpConnections: false,
      runsUserInstance: false,
    },
    dashboard: {
      state: dashboardState,
      enabled: dashboardEnabled,
      endpoint: dashboardBaseUrl ? `${dashboardBaseUrl}/dashboard/session` : null,
      credential: 'DASHBOARD_ACCESS_TOKEN',
    },
    xinchaoMcp: {
      state: mcpState,
      enabled: mcpEnabled && oauthEnabled,
      endpoint: mcpBaseUrl ? `${mcpBaseUrl}/mcp` : null,
      credential: 'OAUTH_APPROVAL_TOKEN',
    },
    externalMemory: {
      state: memoryConnectionState(config),
      urlConfigured: Boolean(String(config.ombre?.url ?? '').trim()),
      readEnabled: Boolean(config.ombre?.readEnabled),
      writeEnabled: Boolean(config.ombre?.writeEnabled),
      publicConnectorTarget: false,
      role: 'internal-memory-backend',
    },
    rules: [
      '公开网页只负责展示，不是 MCP 端点，也不会替用户运行心潮。',
      'AI 连接器只连接用户自己的心潮地址加 /mcp。',
      'OB 地址只供心潮内部调用，不填入公开网页，也不作为心潮连接器地址。',
    ],
  };
}
