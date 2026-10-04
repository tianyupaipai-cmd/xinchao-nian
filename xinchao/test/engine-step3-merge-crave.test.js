import assert from 'node:assert/strict';
import test from 'node:test';

import { DRIVE_KEYS, canonicalDriveKey } from '../src/dimensions.js';
import { newState, settleState } from '../src/engine.js';

const T0 = new Date('2026-09-30T12:00:00.000Z');

test('step 3: 馋她 is folded into 想她 — old saves keep the higher of the two, no separate crave left', () => {
  assert.ok(!DRIVE_KEYS.includes('crave'));
  assert.equal(canonicalDriveKey('crave'), 'possess');
  const s = newState(T0);
  s.drives.possess = 0.64; s.drives.crave = 0.46;
  const a = settleState(s, T0, 1).state;
  assert.equal(a.drives.crave, undefined);
  assert.ok(Math.abs(a.drives.possess - 0.64) < 0.01, `possess ${a.drives.possess}`);
  const t = newState(T0);
  t.drives.possess = 0.40; t.drives.crave = 0.70;
  const b = settleState(t, T0, 1).state;
  assert.ok(Math.abs(b.drives.possess - 0.70) < 0.01, `possess ${b.drives.possess}`);
});
