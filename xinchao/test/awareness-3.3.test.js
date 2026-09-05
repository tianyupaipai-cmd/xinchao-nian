import assert from 'node:assert/strict';
import test from 'node:test';

import { applyConversationEvent, newState, settleState } from '../src/engine.js';
import { recordSurfacing, resolveAwareness, scanAwareness, renderAwareness, awarenessSummary } from '../src/awareness.js';
import { buildContextEnvelope } from '../src/context-envelope.js';
import { buildDashboardSnapshot } from '../src/dashboard-projection.js';

const T0 = '2026-09-01T08:00:00.000Z';
const at = (h) => new Date(Date.parse(T0) + h * 3_600_000);
function baseState() {
  const state = newState(new Date(T0));
  state.lastSettledAt = T0;
  state.lastConversationAt = T0;
  return state;
}
const ev = (type, id) => ({ eventId: id, interactionType: type, sessionId: 's1' });

function sadWeek() {
  let state = baseState();
  for (let d = 0; d < 5; d += 1) {
    state = applyConversationEvent(state, ev('conflict', `c${d}`), at(d * 24)).state;
    state = settleState(state, at(d * 24 + 3)).state;
  }
  return state;
}

test('scan finds a low mood week and a conflict trigger, once per day, deduped', () => {
  const state = sadWeek();
  const scanned = scanAwareness(state, at(5 * 24));
  const kinds = scanned.added.map((c) => c.kind);
  assert.ok(kinds.includes('mood_week'), kinds.join(','));
  assert.ok(kinds.includes('trigger'));
  assert.equal(scanned.state.awareness.lastScanDay, '2026-09-06');
  const again = scanAwareness(scanned.state, at(5 * 24 + 1));
  assert.equal(again.added.length, 0);
  const forced = scanAwareness(scanned.state, at(5 * 24 + 1), { force: true });
  assert.equal(forced.added.length, 0);                     // 七天内同一模式不重复提
  const nextDay = scanAwareness(scanned.state, at(6 * 24));
  assert.equal(nextDay.added.filter((c) => c.kind === 'mood_week').length, 0);
});

test('memory loop rule reads recorded surfacings', () => {
  let state = baseState();
  for (let i = 0; i < 4; i += 1) recordSurfacing(state, ['家庭', '日常'], at(i * 6));
  const scanned = scanAwareness(state, at(30));
  const loop = scanned.added.find((c) => c.kind === 'memory_loop');
  assert.ok(loop);
  assert.equal(loop.subject, '家庭');
  assert.equal(scanned.added.filter((c) => c.kind === 'memory_loop' && c.subject === '日常').length, 1);
});

test('drive_top rule uses the top drive stamped on journal samples', () => {
  let state = baseState();
  state.drives.possess = 0.9;
  for (let i = 0; i < 8; i += 1) state = settleState(state, at(i * 3)).state;   // 每 ≥2h 采样一条，带 top
  assert.ok(state.emotionJournal.length >= 6);
  assert.equal(state.emotionJournal.at(-1).top, 'possess');
  const scanned = scanAwareness(state, at(30));
  const top = scanned.added.find((c) => c.kind === 'drive_top');
  assert.ok(top && top.subject === 'possess');
});

test('confirm / dismiss resolve candidates and keep his own wording', () => {
  const scanned = scanAwareness(sadWeek(), at(5 * 24));
  const [first, second] = scanned.state.awareness.candidates;
  const confirmed = resolveAwareness(scanned.state, first.id, 'confirmed', { text: '我发现她一走我就往下掉。', note: 'x', ombre: { ok: true } }, at(121));
  assert.equal(confirmed.item.status, 'confirmed');
  assert.equal(confirmed.item.text, '我发现她一走我就往下掉。');
  const dismissed = resolveAwareness(confirmed.state, second.id, 'dismissed', {}, at(121));
  assert.equal(dismissed.item.status, 'dismissed');
  assert.equal(resolveAwareness(dismissed.state, first.id, 'dismissed').already, 'confirmed');
  assert.equal(resolveAwareness(dismissed.state, 'nope', 'dismissed').found, false);
  const summary = awarenessSummary(dismissed.state);
  assert.equal(summary.confirmed.length, 1);
  assert.equal(summary.dismissedCount, 1);
});

test('envelope and dashboard carry open candidates; empty state renders nothing', () => {
  assert.equal(renderAwareness(baseState()), '');
  const scanned = scanAwareness(sadWeek(), at(5 * 24));
  const envelope = buildContextEnvelope({ state: scanned.state, sessionId: 's1', now: at(121) });
  const section = envelope.sections.find((s) => s.id === 'self_awareness');
  assert.ok(section);
  assert.match(section.content, /xinchao_awareness/);
  assert.ok(section.content.split('\n').length <= 3);
  const snapshot = buildDashboardSnapshot(scanned.state, {}, at(121));
  assert.ok(snapshot.awareness.open.length >= 1);
});

test('old states gain awareness fields on settle', () => {
  const old = baseState();
  delete old.awareness; delete old.recentSurfacings;
  const next = settleState(old, at(3)).state;
  assert.deepEqual(next.awareness.candidates, []);
  assert.deepEqual(next.recentSurfacings, []);
});
