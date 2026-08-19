import assert from 'node:assert/strict';
import test from 'node:test';

import { applyConversationEvent, newState, settleState } from '../src/engine.js';

function baseState() {
  const state = newState(new Date('2026-08-19T08:00:00.000Z'));
  state.lastSettledAt = '2026-08-19T08:00:00.000Z';
  state.lastConversationAt = '2026-08-19T08:00:00.000Z';
  state.drives = Object.fromEntries(Object.keys(state.drives).map((key) => [key, 0.15]));
  return state;
}

test('old schema state upgrades additively without resetting drives', () => {
  const old = baseState();
  old.schemaVersion = 7;
  delete old.pending;
  delete old.satisfactionPlateaus;
  old.drives.possess = 0.63;
  const result = settleState(old, new Date('2026-08-19T08:00:00.000Z'));
  assert.equal(result.state.schemaVersion, 8);
  assert.equal(result.state.drives.possess, 0.63);
  assert.deepEqual(result.state.pending, []);
  assert.deepEqual(result.state.satisfactionPlateaus, {});
});

test('anger suppresses only natural possess growth and grief lifts crave/monitor growth', () => {
  const calm = baseState();
  const coupled = baseState();
  coupled.drives.anger = 0.8;
  coupled.drives.grieve = 0.8;
  const now = new Date('2026-08-19T09:00:00.000Z');
  const calmResult = settleState(calm, now, 9999).state;
  const coupledResult = settleState(coupled, now, 9999).state;
  assert.ok(coupledResult.drives.possess < calmResult.drives.possess);
  assert.ok(coupledResult.drives.crave > calmResult.drives.crave);
  assert.ok(coupledResult.drives.monitor > calmResult.drives.monitor);
});

test('satisfaction plateau pauses time growth but lets a real event pass through', () => {
  const state = baseState();
  state.drives.share = 0.6;
  const satisfied = applyConversationEvent(
    state,
    { satisfiedDrives: ['share'] },
    new Date('2026-08-19T09:00:00.000Z'),
    { satisfactionPlateauHours: 2 },
  ).state;
  const afterSatisfaction = satisfied.drives.share;
  const oneHourLater = settleState(
    satisfied,
    new Date('2026-08-19T10:00:00.000Z'),
    9999,
    { satisfactionPlateauHours: 2 },
  ).state;
  assert.equal(oneHourLater.drives.share, afterSatisfaction);

  const eventChanged = applyConversationEvent(
    oneHourLater,
    { driveDeltas: { share: 0.1 } },
    new Date('2026-08-19T10:05:00.000Z'),
  ).state;
  assert.equal(eventChanged.drives.share, Number((afterSatisfaction + 0.1).toFixed(4)));

  const afterExpiry = settleState(
    eventChanged,
    new Date('2026-08-19T12:05:00.000Z'),
    9999,
    { satisfactionPlateauHours: 2 },
  ).state;
  assert.ok(afterExpiry.drives.share > eventChanged.drives.share);
  assert.equal(afterExpiry.satisfactionPlateaus.share, undefined);
});
