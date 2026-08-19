import test from 'node:test';
import assert from 'node:assert/strict';
import { bridgeDeliveryFromDashboard } from '../src/bridge-queue.js';

test('Dashboard feedback preserves user_feedback reason', () => {
  const result = bridgeDeliveryFromDashboard({
    event_id: 'feedback-20260819-001',
    message: '  星图打不开\n请检查  ',
    reason: 'user_feedback',
  }, new Date('2026-08-19T08:00:00Z'));
  assert.equal(result.reason, 'user_feedback');
  assert.equal(result.message, '星图打不开 请检查');
});

test('future delivery defaults to scheduled_interaction', () => {
  const result = bridgeDeliveryFromDashboard({
    event_id: 'scheduled-20260819-001',
    message: '明天再提醒我',
    deliver_after: '2026-08-20T08:00:00Z',
  }, new Date('2026-08-19T08:00:00Z'));
  assert.equal(result.reason, 'scheduled_interaction');
});
