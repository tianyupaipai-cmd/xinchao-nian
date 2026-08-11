import { createHash, randomBytes, timingSafeEqual } from 'node:crypto';

const COOKIE_NAME = 'xinchao_dashboard';

function safeEqual(leftValue, rightValue) {
  const left = Buffer.from(String(leftValue ?? ''));
  const right = Buffer.from(String(rightValue ?? ''));
  return left.length === right.length && timingSafeEqual(left, right);
}

function digest(value) {
  return createHash('sha256').update(String(value ?? ''), 'utf8').digest('hex');
}

function cookies(header = '') {
  return Object.fromEntries(String(header).split(';').map((part) => {
    const index = part.indexOf('=');
    if (index < 0) return ['', ''];
    return [part.slice(0, index).trim(), decodeURIComponent(part.slice(index + 1).trim())];
  }).filter(([key]) => key));
}

export class DashboardAuth {
  constructor(options = {}) {
    this.enabled = Boolean(options.enabled);
    this.accessToken = String(options.accessToken ?? '');
    this.ttlSeconds = Math.max(900, Math.min(604800, Number(options.ttlSeconds) || 43200));
    this.secureCookies = Boolean(options.secureCookies);
    this.sessions = new Map();
    this.failures = new Map();
  }

  verifyAccessToken(value, remoteAddress = 'unknown', now = new Date()) {
    if (!this.enabled || this.rateLimited(remoteAddress, now)) return false;
    const valid = safeEqual(value, this.accessToken);
    if (valid) this.failures.delete(remoteAddress);
    else this.recordFailure(remoteAddress, now);
    return valid;
  }

  rateLimited(remoteAddress, now = new Date()) {
    const entry = this.failures.get(remoteAddress);
    if (!entry) return false;
    if (now.getTime() - entry.startedAt >= 60_000) {
      this.failures.delete(remoteAddress);
      return false;
    }
    return entry.count >= 8;
  }

  recordFailure(remoteAddress, now = new Date()) {
    const current = this.failures.get(remoteAddress);
    if (!current || now.getTime() - current.startedAt >= 60_000) {
      this.failures.set(remoteAddress, { count: 1, startedAt: now.getTime() });
      return;
    }
    current.count += 1;
  }

  createSession(now = new Date()) {
    const token = randomBytes(32).toString('base64url');
    const expiresAt = new Date(now.getTime() + this.ttlSeconds * 1000);
    this.sessions.set(digest(token), expiresAt.getTime());
    this.prune(now);
    return { token, expiresAt: expiresAt.toISOString() };
  }

  validateRequest(request, now = new Date()) {
    if (!this.enabled) return false;
    // 同源 Dashboard 使用 HttpOnly Cookie；跨源浏览器直连使用同一枚短期会话
    // token 的 Authorization 通道。长期 Dashboard 口令仍然只能用于换取会话。
    const token = cookies(request.headers.cookie)[COOKIE_NAME]
      || (request.headers.authorization ?? '').replace(/^Bearer\s+/i, '').trim();
    if (!token) return false;
    const expiresAt = this.sessions.get(digest(token));
    if (!expiresAt || expiresAt <= now.getTime()) {
      if (expiresAt) this.sessions.delete(digest(token));
      return false;
    }
    return true;
  }

  destroyRequestSession(request) {
    const token = cookies(request.headers.cookie)[COOKIE_NAME]
      || (request.headers.authorization ?? '').replace(/^Bearer\s+/i, '').trim();
    if (token) this.sessions.delete(digest(token));
  }

  sessionCookie(token) {
    return [
      `${COOKIE_NAME}=${encodeURIComponent(token)}`,
      'Path=/dashboard',
      'HttpOnly',
      'SameSite=Strict',
      `Max-Age=${this.ttlSeconds}`,
      this.secureCookies ? 'Secure' : '',
    ].filter(Boolean).join('; ');
  }

  clearCookie() {
    return [
      `${COOKIE_NAME}=`,
      'Path=/dashboard',
      'HttpOnly',
      'SameSite=Strict',
      'Max-Age=0',
      this.secureCookies ? 'Secure' : '',
    ].filter(Boolean).join('; ');
  }

  prune(now = new Date()) {
    for (const [key, expiresAt] of this.sessions) {
      if (expiresAt <= now.getTime()) this.sessions.delete(key);
    }
  }
}
