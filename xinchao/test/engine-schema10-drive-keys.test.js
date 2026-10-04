import assert from 'node:assert/strict';
import test from 'node:test';

import { newState, settleAndApplyConversationEvent, topDrives, pickIntent } from '../src/engine.js';
import { DRIVE_KEYS, DRIVE_SHORT } from '../src/dimensions.js';
import { DRIVE_SHORT as SIGNAL_SHORT } from '../src/self-signals.js';

const T0 = new Date('2026-09-27T02:00:00.000Z');

function legacy() {
  const s = newState(T0);
  s.schemaVersion = 9;
  s.drives.retired = 0.9;                 // 名单里已经没有的旧 key
  delete s.drives.curiosity;              // 名单里有、存档里缺的 key
  s.satisfactionPlateaus = { retired: T0.toISOString(), share: T0.toISOString() };
  s.driveTrail = [{ at: T0.toISOString(), drives: { retired: 0.5, share: 0.3 } }];
  s.lastConversationAt = T0.toISOString();
  return s;
}

test('schema 10：孤儿 key 丢掉、缺的补上，topDrives/pickIntent 不再因旧 key 崩', () => {
  const r = settleAndApplyConversationEvent(legacy(), { eventId: 'm1' }, new Date(T0.getTime() + 60_000), {});
  const s = r.state;
  assert.equal(s.schemaVersion, 10);
  assert.deepEqual(Object.keys(s.drives).sort(), [...DRIVE_KEYS].sort());
  assert.ok(Number.isFinite(s.drives.curiosity));
  assert.equal(s.satisfactionPlateaus.retired, undefined);
  assert.ok(s.driveTrail.every((p) => !('retired' in p.drives)));
  assert.doesNotThrow(() => topDrives(s));
  assert.ok(topDrives(s).every((d) => DRIVE_KEYS.includes(d.key)));
  const withOrphan = { ...s, drives: { ...s.drives, retired: 0.99 } };
  assert.doesNotThrow(() => topDrives(withOrphan));
  assert.notEqual(pickIntent(withOrphan, () => 0)?.key, 'retired');
});

test('schema 10：短名表全系统一份，覆盖每一个驱力', () => {
  assert.equal(SIGNAL_SHORT, DRIVE_SHORT);
  for (const k of DRIVE_KEYS) assert.ok(DRIVE_SHORT[k], `${k} 缺短名`);
});
