import test from 'node:test';
import assert from 'node:assert/strict';
import { DashboardAuth } from '../src/dashboard-auth.js';
import { loadConfig } from '../src/config.js';

function dashboardAuth() {
  return new DashboardAuth({ enabled: true, accessToken: 'x'.repeat(40), ttlSeconds: 3600 });
}

test('dashboard session token supports cookie and browser header channels', () => {
  const auth = dashboardAuth();
  const { token } = auth.createSession();

  assert.equal(auth.validateRequest({ headers: { cookie: `xinchao_dashboard=${token}` } }), true);
  assert.equal(auth.validateRequest({ headers: { authorization: `Bearer ${token}` } }), true);
  assert.equal(auth.validateRequest({ headers: { authorization: `Bearer ${'x'.repeat(40)}` } }), false);
});

test('dashboard allowed origins are closed by default and normalized when configured', () => {
  const previous = process.env.DASHBOARD_ALLOWED_ORIGINS;
  try {
    delete process.env.DASHBOARD_ALLOWED_ORIGINS;
    assert.deepEqual(loadConfig().dashboard.allowedOrigins, []);

    process.env.DASHBOARD_ALLOWED_ORIGINS = 'https://xinchaomind.uk/, https://preview.example.com';
    assert.deepEqual(loadConfig().dashboard.allowedOrigins, [
      'https://xinchaomind.uk',
      'https://preview.example.com',
    ]);
  } finally {
    if (previous === undefined) delete process.env.DASHBOARD_ALLOWED_ORIGINS;
    else process.env.DASHBOARD_ALLOWED_ORIGINS = previous;
  }
});
