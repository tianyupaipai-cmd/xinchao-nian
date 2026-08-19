import test from 'node:test';
import assert from 'node:assert/strict';
import { buildConnectionDiagnostics, memoryConnectionState } from '../src/connection-diagnostics.js';
import { buildConnectionManifest, buildDashboardSnapshot } from '../src/dashboard-projection.js';

function config(overrides = {}) {
  return {
    identity: {},
    dashboard: { enabled: true, publicBaseUrl: 'https://mind.example.com', includePrivateText: false, ...overrides.dashboard },
    mcp: { enabled: true, ...overrides.mcp },
    oauth: { enabled: true, publicBaseUrl: 'https://mind.example.com', ...overrides.oauth },
    ombre: { url: 'http://ombre:8000/mcp', token: 'memory-token', readEnabled: true, writeEnabled: false, ...overrides.ombre },
    context: {}, bark: {}, bridge: {},
  };
}

test('diagnostics keep public web, Xinchao MCP and OB roles separate', () => {
  const result = buildConnectionDiagnostics(config());
  assert.equal(result.publicVisualizer.url, 'https://xinchaomind.uk');
  assert.equal(result.publicVisualizer.acceptsMcpConnections, false);
  assert.equal(result.xinchaoMcp.endpoint, 'https://mind.example.com/mcp');
  assert.equal(result.externalMemory.publicConnectorTarget, false);
  assert.equal(result.externalMemory.role, 'internal-memory-backend');
});

test('memory diagnostics explain the actual missing configuration', () => {
  assert.equal(memoryConnectionState(config({ ombre: { url: '', token: '', readEnabled: false } })), 'ob_url_missing');
  assert.equal(memoryConnectionState(config({ ombre: { readEnabled: false } })), 'ob_read_disabled');
  assert.equal(memoryConnectionState(config({ ombre: { token: '' } })), 'ob_token_missing');
  assert.equal(memoryConnectionState(config()), 'ob_configured');
});

test('manifest never borrows Dashboard URL for MCP or MCP URL for Dashboard', () => {
  const result = buildConnectionManifest(config({
    dashboard: { publicBaseUrl: 'https://dashboard.example.com' },
    oauth: { publicBaseUrl: '' },
  }));
  const dashboard = result.profiles.find((item) => item.id === 'web-dashboard');
  const mcp = result.profiles.find((item) => item.id === 'remote-mcp-oauth');
  assert.equal(dashboard.endpoint, 'https://dashboard.example.com/dashboard/session');
  assert.equal(mcp.enabled, false);
  assert.equal(mcp.endpoint, null);
  assert.equal(result.connections.xinchaoMcp.state, 'mcp_base_url_missing');
});

test('snapshot includes safe structured connection diagnostics', () => {
  const result = buildDashboardSnapshot({}, config(), new Date('2026-08-19T00:00:00Z'));
  assert.equal(result.connections.externalMemory.state, 'ob_configured');
  assert.equal(JSON.stringify(result.connections).includes('memory-token'), false);
});
