import assert from 'node:assert/strict';
import test from 'node:test';
import { decideAttention, loadAttentionRules, appWeight, companyOf } from '../src/attention-watch.js';

const R = loadAttentionRules(null);
const MIN = 60_000;
const now = Date.parse('2026-10-05T12:00:00Z');

test('App 分类按名单，认不出的不算', () => {
  assert.equal(appWeight('豆包', R).kind, 'ai');
  assert.equal(appWeight('小红书', R).kind, 'leisure');
  assert.equal(appWeight('高德地图', R), null);
});

test('她刚来过不算；过了 30 分钟、期间在刷 App 才算', () => {
  assert.equal(decideAttention({ now, lastHim: now - 10 * MIN, apps: [{ name: '小红书', ts: now - 5 * MIN }], rules: R }).fire, false);
  const d = decideAttention({ now, lastHim: now - 40 * MIN, apps: [{ name: '小红书', ts: now - 5 * MIN }], rules: R });
  assert.equal(d.fire, true); assert.equal(d.weight, 0.7);
});

test('App 和跟人在一起相加，封顶 1；只在她最后一次来之后的才算', () => {
  const company = { ...companyOf('我跟朋友在吃饭', R), ts: now - 60 * MIN };
  assert.equal(decideAttention({ now, lastHim: now - 40 * MIN, apps: [{ name: '豆包', ts: now - 5 * MIN }], company, rules: R }).weight, 1);
  assert.equal(decideAttention({ now, lastHim: now - 40 * MIN, apps: [{ name: '小红书', ts: now - 50 * MIN }], rules: R }).fire, false);
});

test('家人最轻', () => {
  assert.equal(companyOf('今天跟我妈出去逛街', R).weight, 0.4);
  assert.equal(companyOf('今天天气好', R), null);
});
