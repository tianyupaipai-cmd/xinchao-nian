import { createHash, randomBytes, timingSafeEqual } from 'node:crypto';
import { chmod, mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import { dirname } from 'node:path';

const CODE_TTL_MS = 5 * 60_000;
const CLIENT_TTL_MS = 365 * 24 * 60 * 60_000;
const MAX_CLIENTS = 1024;
const MAX_REDIRECT_URIS = 10;
const PKCE_PATTERN = /^[A-Za-z0-9._~-]{43,128}$/;
const FORBIDDEN_REDIRECT_SCHEMES = new Set([
  'about:', 'blob:', 'data:', 'file:', 'ftp:', 'javascript:', 'vbscript:',
]);

function base64url(bytes) {
  return Buffer.from(bytes).toString('base64url');
}

function digest(value) {
  return createHash('sha256').update(String(value)).digest('hex');
}

function safeEqual(leftValue, rightValue) {
  const left = Buffer.from(String(leftValue));
  const right = Buffer.from(String(rightValue));
  return left.length === right.length && timingSafeEqual(left, right);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function normalizeResource(value) {
  try {
    const parsed = new URL(String(value));
    if (!['http:', 'https:'].includes(parsed.protocol) || parsed.hash) return '';
    parsed.hash = '';
    parsed.search = '';
    parsed.pathname = parsed.pathname.replace(/\/+$/, '') || '/';
    return parsed.toString().replace(/\/$/, '');
  } catch {
    return '';
  }
}

function validRedirectUri(value) {
  if (typeof value !== 'string' || value.length < 1 || value.length > 2048) return false;
  try {
    const parsed = new URL(value);
    if (parsed.hash || parsed.username || parsed.password || FORBIDDEN_REDIRECT_SCHEMES.has(parsed.protocol)) {
      return false;
    }
    if (parsed.protocol === 'https:') return Boolean(parsed.hostname);
    if (parsed.protocol === 'http:') {
      return ['localhost', '127.0.0.1', '::1'].includes(parsed.hostname);
    }
    return Boolean(parsed.protocol && (parsed.hostname || parsed.pathname));
  } catch {
    return false;
  }
}

function json(response, status, value, extraHeaders = {}) {
  response.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'no-store',
    ...extraHeaders,
  });
  response.end(JSON.stringify(value));
}

function html(response, status, value) {
  response.writeHead(status, {
    'Content-Type': 'text/html; charset=utf-8',
    'Cache-Control': 'no-store',
    'Content-Security-Policy': [
      "default-src 'none'",
      "style-src 'unsafe-inline'",
      "form-action 'self' https: http://localhost:* http://127.0.0.1:*",
      "base-uri 'none'",
      "frame-ancestors 'none'",
    ].join('; '),
    'X-Content-Type-Options': 'nosniff',
    'X-Frame-Options': 'DENY',
  });
  response.end(value);
}

async function rawBody(request, limit = 64 * 1024) {
  let raw = '';
  for await (const chunk of request) {
    raw += chunk;
    if (raw.length > limit) throw new Error('request body too large');
  }
  return raw;
}

function oauthError(response, status, error, description = '') {
  const value = { error };
  if (description) value.error_description = description;
  json(response, status, value);
}

function freshState() {
  return {
    version: 1,
    clients: {},
    accessTokens: {},
    refreshTokens: {},
  };
}

export class OAuthProvider {
  constructor(config, onEvent = () => {}) {
    this.enabled = Boolean(config.enabled);
    this.baseUrl = String(config.publicBaseUrl ?? '').replace(/\/+$/, '');
    this.resource = `${this.baseUrl}/mcp`;
    this.approvalToken = String(config.approvalToken ?? '');
    this.statePath = String(config.statePath ?? '/app/state/oauth.json');
    this.accessTtlSeconds = Number(config.accessTtlSeconds ?? 86400);
    this.refreshTtlSeconds = Number(config.refreshTtlSeconds ?? 31536000);
    this.scope = 'xinchao';
    this.state = freshState();
    this.codes = new Map();
    this.savePromise = Promise.resolve();
    this.onEvent = onEvent;
  }

  async init() {
    if (!this.enabled) return;
    if (!this.baseUrl.startsWith('https://')) {
      throw new Error('OAUTH_PUBLIC_BASE_URL must be an https URL');
    }
    if (this.approvalToken.length < 16) {
      throw new Error('OAUTH_APPROVAL_TOKEN must contain at least 16 characters');
    }
    try {
      const parsed = JSON.parse(await readFile(this.statePath, 'utf8'));
      if (parsed && parsed.version === 1) {
        this.state = {
          ...freshState(),
          ...parsed,
          clients: parsed.clients ?? {},
          accessTokens: parsed.accessTokens ?? {},
          refreshTokens: parsed.refreshTokens ?? {},
        };
      }
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
    }
    this.cleanup();
    await this.persist();
  }

  cleanup(now = Date.now()) {
    for (const [clientId, client] of Object.entries(this.state.clients)) {
      if (!client || client.expiresAt <= now) delete this.state.clients[clientId];
    }
    for (const [tokenHash, token] of Object.entries(this.state.accessTokens)) {
      if (!token || token.expiresAt <= now) delete this.state.accessTokens[tokenHash];
    }
    for (const [tokenHash, token] of Object.entries(this.state.refreshTokens)) {
      if (!token || token.expiresAt <= now) delete this.state.refreshTokens[tokenHash];
    }
    for (const [code, record] of this.codes.entries()) {
      if (!record || record.expiresAt <= now) this.codes.delete(code);
    }
  }

  persist() {
    const snapshot = `${JSON.stringify(this.state, null, 2)}\n`;
    this.savePromise = this.savePromise.then(async () => {
      await mkdir(dirname(this.statePath), { recursive: true });
      const tempPath = `${this.statePath}.${process.pid}.${randomBytes(6).toString('hex')}.tmp`;
      await writeFile(tempPath, snapshot, { mode: 0o600 });
      await chmod(tempPath, 0o600);
      await rename(tempPath, this.statePath);
      await chmod(this.statePath, 0o600);
    });
    return this.savePromise;
  }

  protectedResourceMetadata() {
    return {
      resource: this.resource,
      authorization_servers: [this.baseUrl],
      bearer_methods_supported: ['header'],
      scopes_supported: [this.scope],
    };
  }

  authorizationServerMetadata() {
    return {
      issuer: this.baseUrl,
      authorization_endpoint: `${this.baseUrl}/oauth/authorize`,
      token_endpoint: `${this.baseUrl}/oauth/token`,
      registration_endpoint: `${this.baseUrl}/oauth/register`,
      response_types_supported: ['code'],
      grant_types_supported: ['authorization_code', 'refresh_token'],
      code_challenge_methods_supported: ['S256'],
      token_endpoint_auth_methods_supported: ['none'],
      scopes_supported: [this.scope],
    };
  }

  wwwAuthenticate() {
    const metadata = `${this.baseUrl}/.well-known/oauth-protected-resource/mcp`;
    return `Bearer realm="xinchao-mcp", resource_metadata="${metadata}", scope="${this.scope}"`;
  }

  validateAccessToken(token) {
    if (!this.enabled || !token) return false;
    this.cleanup();
    const record = this.state.accessTokens[digest(token)];
    return Boolean(
      record
      && record.expiresAt > Date.now()
      && normalizeResource(record.resource) === normalizeResource(this.resource),
    );
  }

  validResource(requested) {
    if (!requested) return true;
    const normalized = normalizeResource(requested);
    return normalized === normalizeResource(this.resource)
      || normalized === normalizeResource(this.baseUrl);
  }

  clientForAuthorize(params) {
    this.cleanup();
    const clientId = String(params.get('client_id') ?? '');
    const redirectUri = String(params.get('redirect_uri') ?? '');
    const responseType = String(params.get('response_type') ?? '');
    const codeChallenge = String(params.get('code_challenge') ?? '');
    const codeChallengeMethod = String(params.get('code_challenge_method') ?? '');
    const resource = String(params.get('resource') ?? '');
    const scope = String(params.get('scope') ?? this.scope);
    const client = this.state.clients[clientId];
    if (!client) return { error: 'unknown client_id' };
    if (!client.redirectUris.includes(redirectUri)) return { error: 'redirect_uri mismatch' };
    if (responseType !== 'code') return { error: 'response_type must be code' };
    if (codeChallengeMethod !== 'S256' || !PKCE_PATTERN.test(codeChallenge)) {
      return { error: 'PKCE S256 is required' };
    }
    if (!this.validResource(resource)) return { error: 'invalid resource' };
    if (scope !== this.scope) return { error: 'invalid scope' };
    return {
      client,
      clientId,
      redirectUri,
      codeChallenge,
      resource: this.resource,
      scope,
      state: String(params.get('state') ?? ''),
    };
  }

  authorizeHtml(values, error = '') {
    const e = escapeHtml;
    const clientName = e(values.client?.clientName ?? 'MCP Client');
    const errorBlock = error
      ? `<p class="error">${e(error)}</p>`
      : '';
    return `<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>心潮 · 授权连接</title>
<style>
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:#101316;color:#edf2f5;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
.card{width:min(420px,90vw);padding:34px;border:1px solid #34414a;border-radius:20px;background:#192026;box-shadow:0 24px 70px #0008}
h1{margin:0 0 8px;font-size:25px;color:#7ad7cf}.sub{margin:0 0 24px;color:#aab8c0;line-height:1.6}.meta{padding:12px;border-radius:10px;background:#11171b;color:#86979f;font-size:12px;line-height:1.55;word-break:break-all}
input{width:100%;margin:18px 0 12px;padding:13px 14px;border:1px solid #46555f;border-radius:10px;background:#0e1418;color:#fff;font-size:15px}
button{width:100%;padding:13px;border:0;border-radius:10px;background:#65cec4;color:#09201e;font-size:15px;font-weight:700;cursor:pointer}.note{color:#75858e;font-size:12px;line-height:1.55}.error{color:#ff8c8c;font-size:13px}
</style></head><body><main class="card">
<h1>心潮动态心智系统</h1>
<p class="sub">确认授权 Claude 连接你的心潮 MCP。授权只开放心潮上下文和窗口事件工具，不会接收聊天正文。</p>
<div class="meta">请求方：${clientName}<br>回调：${e(values.redirectUri)}</div>
<form method="post" action="/oauth/authorize">
<input type="hidden" name="client_id" value="${e(values.clientId)}">
<input type="hidden" name="redirect_uri" value="${e(values.redirectUri)}">
<input type="hidden" name="state" value="${e(values.state)}">
<input type="hidden" name="code_challenge" value="${e(values.codeChallenge)}">
<input type="hidden" name="code_challenge_method" value="S256">
<input type="hidden" name="response_type" value="code">
<input type="hidden" name="resource" value="${e(values.resource)}">
<input type="hidden" name="scope" value="${e(values.scope)}">
<input type="password" name="approval_token" placeholder="输入心潮授权口令" autocomplete="current-password" autofocus required>
<button type="submit">授权并连接</button>
</form>${errorBlock}
<p class="note">访问令牌会定期过期并由 Claude 自动刷新。若不是你发起的连接，请直接关闭本页。</p>
</main></body></html>`;
  }

  async registerClient(request, response) {
    let data;
    try {
      data = JSON.parse(await rawBody(request));
    } catch {
      return oauthError(response, 400, 'invalid_client_metadata', 'invalid JSON');
    }
    const redirectUris = data?.redirect_uris;
    if (
      !Array.isArray(redirectUris)
      || redirectUris.length < 1
      || redirectUris.length > MAX_REDIRECT_URIS
      || redirectUris.some((uri) => !validRedirectUri(uri))
    ) {
      return oauthError(
        response,
        400,
        'invalid_redirect_uri',
        'redirect_uris must contain 1-10 safe absolute callback URIs',
      );
    }
    this.cleanup();
    if (Object.keys(this.state.clients).length >= MAX_CLIENTS) {
      return oauthError(response, 429, 'temporarily_unavailable');
    }
    const clientId = base64url(randomBytes(24));
    const clientName = String(data.client_name ?? 'MCP Client').trim().slice(0, 200) || 'MCP Client';
    const uniqueRedirects = [...new Set(redirectUris)];
    this.state.clients[clientId] = {
      clientName,
      redirectUris: uniqueRedirects,
      issuedAt: Date.now(),
      expiresAt: Date.now() + CLIENT_TTL_MS,
    };
    await this.persist();
    this.onEvent('oauth_client_registered', { clientName });
    return json(response, 201, {
      client_id: clientId,
      client_id_issued_at: Math.floor(Date.now() / 1000),
      client_name: clientName,
      redirect_uris: uniqueRedirects,
      token_endpoint_auth_method: 'none',
      grant_types: ['authorization_code', 'refresh_token'],
      response_types: ['code'],
    });
  }

  async authorizeGet(response, url) {
    const values = this.clientForAuthorize(url.searchParams);
    if (values.error) return oauthError(response, 400, 'invalid_request', values.error);
    return html(response, 200, this.authorizeHtml(values));
  }

  async authorizePost(request, response) {
    const form = new URLSearchParams(await rawBody(request));
    const values = this.clientForAuthorize(form);
    if (values.error) return oauthError(response, 400, 'invalid_request', values.error);
    if (!safeEqual(form.get('approval_token') ?? '', this.approvalToken)) {
      this.onEvent('oauth_authorization_denied');
      return html(response, 401, this.authorizeHtml(values, '授权口令不正确'));
    }
    const code = base64url(randomBytes(32));
    this.codes.set(code, {
      clientId: values.clientId,
      redirectUri: values.redirectUri,
      codeChallenge: values.codeChallenge,
      resource: values.resource,
      scope: values.scope,
      expiresAt: Date.now() + CODE_TTL_MS,
    });
    const redirect = new URL(values.redirectUri);
    redirect.searchParams.set('code', code);
    if (values.state) redirect.searchParams.set('state', values.state);
    this.onEvent('oauth_authorization_approved', {
      clientName: values.client.clientName,
      redirectHost: redirect.host,
      statePresent: Boolean(values.state),
    });
    response.writeHead(302, { Location: redirect.toString(), 'Cache-Control': 'no-store' });
    response.end();
  }

  issueTokens(clientId, resource) {
    const accessToken = base64url(randomBytes(32));
    const refreshToken = base64url(randomBytes(32));
    const now = Date.now();
    this.state.accessTokens[digest(accessToken)] = {
      clientId,
      resource,
      scope: this.scope,
      expiresAt: now + this.accessTtlSeconds * 1000,
    };
    this.state.refreshTokens[digest(refreshToken)] = {
      clientId,
      resource,
      scope: this.scope,
      expiresAt: now + this.refreshTtlSeconds * 1000,
    };
    return { accessToken, refreshToken };
  }

  tokenPayload(tokens) {
    return {
      access_token: tokens.accessToken,
      token_type: 'Bearer',
      expires_in: this.accessTtlSeconds,
      refresh_token: tokens.refreshToken,
      refresh_expires_in: this.refreshTtlSeconds,
      scope: this.scope,
    };
  }

  rejectToken(response, status, error, reason) {
    this.onEvent('oauth_token_rejected', { error, reason });
    return oauthError(response, status, error, reason);
  }

  async exchangeToken(request, response) {
    let values;
    try {
      const raw = await rawBody(request);
      const contentType = String(request.headers['content-type'] ?? '').toLowerCase();
      if (contentType.includes('application/json')) {
        const parsed = JSON.parse(raw);
        if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('invalid JSON');
        values = parsed;
      } else {
        values = Object.fromEntries(new URLSearchParams(raw));
      }
    } catch {
      return this.rejectToken(response, 400, 'invalid_request', 'body_parse_failed');
    }
    const grantType = String(values.grant_type ?? '');
    const suppliedClientId = String(values.client_id ?? '');

    if (grantType === 'authorization_code') {
      const code = String(values.code ?? '');
      const record = this.codes.get(code);
      this.codes.delete(code);
      if (!record || record.expiresAt <= Date.now()) {
        return this.rejectToken(response, 400, 'invalid_grant', 'unknown_or_expired_code');
      }
      const clientId = suppliedClientId || record.clientId;
      const verifier = String(values.code_verifier ?? '');
      const redirectUri = String(values.redirect_uri ?? '');
      const requestedResource = String(values.resource ?? '');
      if (
        !this.state.clients[clientId]
        || record.clientId !== clientId
      ) {
        return this.rejectToken(response, 401, 'invalid_client', 'client_id_mismatch');
      }
      if (redirectUri && record.redirectUri !== redirectUri) {
        return this.rejectToken(response, 400, 'invalid_grant', 'redirect_uri_mismatch');
      }
      if (
        requestedResource
        && !this.validResource(requestedResource)
      ) {
        return this.rejectToken(response, 400, 'invalid_target', 'resource_mismatch');
      }
      if (
        !PKCE_PATTERN.test(verifier)
        || base64url(createHash('sha256').update(verifier).digest()) !== record.codeChallenge
      ) {
        return this.rejectToken(response, 400, 'invalid_grant', 'pkce_verification_failed');
      }
      const tokens = this.issueTokens(clientId, record.resource);
      await this.persist();
      this.onEvent('oauth_token_issued');
      return json(response, 200, this.tokenPayload(tokens), { Pragma: 'no-cache' });
    }

    if (grantType === 'refresh_token') {
      const supplied = String(values.refresh_token ?? '');
      const tokenHash = digest(supplied);
      const record = this.state.refreshTokens[tokenHash];
      if (!record || record.expiresAt <= Date.now()) {
        return this.rejectToken(response, 400, 'invalid_grant', 'unknown_or_expired_refresh_token');
      }
      const clientId = suppliedClientId || record.clientId;
      if (!this.state.clients[clientId] || record.clientId !== clientId) {
        return this.rejectToken(response, 401, 'invalid_client', 'client_id_mismatch');
      }
      const requestedResource = String(values.resource ?? '');
      if (
        requestedResource
        && !this.validResource(requestedResource)
      ) {
        return this.rejectToken(response, 400, 'invalid_target', 'resource_mismatch');
      }
      delete this.state.refreshTokens[tokenHash];
      const tokens = this.issueTokens(clientId, record.resource);
      await this.persist();
      this.onEvent('oauth_token_refreshed');
      return json(response, 200, this.tokenPayload(tokens), { Pragma: 'no-cache' });
    }
    return this.rejectToken(response, 400, 'unsupported_grant_type', 'unsupported_grant_type');
  }

  async handle(request, response, url) {
    if (!this.enabled) return false;
    if (
      request.method === 'GET'
      && (url.pathname === '/.well-known/oauth-protected-resource'
        || url.pathname === '/.well-known/oauth-protected-resource/mcp')
    ) {
      json(response, 200, this.protectedResourceMetadata());
      return true;
    }
    if (request.method === 'GET' && url.pathname === '/.well-known/oauth-authorization-server') {
      json(response, 200, this.authorizationServerMetadata());
      return true;
    }
    if (request.method === 'POST' && url.pathname === '/oauth/register') {
      await this.registerClient(request, response);
      return true;
    }
    if (request.method === 'GET' && url.pathname === '/oauth/authorize') {
      await this.authorizeGet(response, url);
      return true;
    }
    if (request.method === 'POST' && url.pathname === '/oauth/authorize') {
      await this.authorizePost(request, response);
      return true;
    }
    if (request.method === 'POST' && url.pathname === '/oauth/token') {
      await this.exchangeToken(request, response);
      return true;
    }
    return false;
  }
}
