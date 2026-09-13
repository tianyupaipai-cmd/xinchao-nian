import test from 'node:test';
import assert from 'node:assert/strict';
import { settleState, newState } from '../src/engine.js';

function withObsession(level) {
  const s = newState(new Date('2026-09-13T04:00:00Z'));
  s.consciousness = 'awake';
  s.lastSettledAt = '2026-09-13T04:00:00.000Z';
  s.lastHeartbeatAt = s.lastSettledAt; s.lastConversationAt = s.lastSettledAt;
  s.drives.reflection = level;
  s.thoughtPool = { flash: [], obsessions: [{ key: 'reflection', text: 'x', intensity: 0.9, feedbacks: 0 }] };
  return s;
}

test('3.3.6 念头回推不越过 0.85', () => {
  const now = new Date('2026-09-13T04:01:00Z');
  const high = settleState(withObsession(0.95), now, 90, {});
  assert.ok((high.state ?? high).drives.reflection <= 0.95, '已经很高就不推');
  const mid = settleState(withObsession(0.80), now, 90, {});
  assert.ok(Math.abs((mid.state ?? mid).drives.reflection - 0.85) < 0.02, '推到 0.85 封顶');
  const low = settleState(withObsession(0.40), now, 90, {});
  assert.ok((low.state ?? low).drives.reflection > 0.55, '低的时候正常推 +0.18');
});
