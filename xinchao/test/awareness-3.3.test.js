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

test('scan keeps only causal kinds, one candidate per day, deduped for a week', () => {
  const state = sadWeek();
  const scanned = scanAwareness(state, at(5 * 24));
  const kinds = scanned.added.map((c) => c.kind);
  assert.deepEqual(kinds, ['trigger']);                       // 3.3.3：本周均值/最常驱力/记忆环不再是候选
  assert.equal(scanned.state.awareness.lastScanDay, '2026-09-06');
  const again = scanAwareness(scanned.state, at(5 * 24 + 1));
  assert.equal(again.added.length, 0);
  const forced = scanAwareness(scanned.state, at(5 * 24 + 1), { force: true });
  assert.equal(forced.added.length, 0);                     // 七天内同一模式不重复提
  const nextDay = scanAwareness(scanned.state, at(6 * 24));
  assert.equal(nextDay.added.length, 0);
});

test('one per day: trigger wins over obsession, obsession comes the next day', () => {
  const state = sadWeek();
  state.thoughtPool = { obsessions: [{ key: 'possess', intensity: 0.8 }] };
  const day1 = scanAwareness(state, at(5 * 24));
  assert.deepEqual(day1.added.map((c) => c.kind), ['trigger']);
  const day2 = scanAwareness(day1.state, at(6 * 24));
  assert.deepEqual(day2.added.map((c) => c.kind), ['obsession']);
});

test('counting rules are gone: surfacings and top drives never become candidates', () => {
  let state = baseState();
  for (let i = 0; i < 6; i += 1) recordSurfacing(state, ['家庭', '日常'], at(i * 6));
  state.drives.possess = 0.9;
  for (let i = 0; i < 8; i += 1) state = settleState(state, at(i * 3)).state;
  const scanned = scanAwareness(state, at(30));
  assert.equal(scanned.added.length, 0);
});

test('open candidates expire after two weeks without being forced on him', () => {
  const scanned = scanAwareness(sadWeek(), at(5 * 24));
  const [c] = scanned.state.awareness.candidates;
  assert.equal(c.status, 'open');
  const later = scanAwareness(scanned.state, at(5 * 24 + 15 * 24));
  assert.equal(later.state.awareness.candidates.find((x) => x.id === c.id).status, 'expired');
  assert.equal(awarenessSummary(later.state).expiredCount, 1);
});

test('confirm / dismiss resolve candidates and keep his own wording', () => {
  const scanned = scanAwareness(sadWeek(), at(5 * 24));
  scanned.state.awareness.candidates.push({ id: 'aw_x', kind: 'soothed', subject: 'week', text: 't', aspect: 'patterns', createdAt: T0, status: 'open', resolvedAt: null, note: null, ombre: null });
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

test('envelope shows candidates only on the review day; dashboard always; empty renders nothing', () => {
  assert.equal(renderAwareness(baseState(), { force: true }), '');
  const scanned = scanAwareness(sadWeek(), at(5 * 24));
  // at(121) = 2026-09-06 17:00 上海 = 周日（默认复盘日）
  const envelope = buildContextEnvelope({ state: scanned.state, sessionId: 's1', now: at(121) });
  const section = envelope.sections.find((s) => s.id === 'self_awareness');
  assert.ok(section);
  assert.match(section.content, /xinchao_awareness/);
  assert.match(section.content, /两周后自动过期/);
  // 周一就不出现
  const monday = buildContextEnvelope({ state: scanned.state, sessionId: 's1', now: at(121 + 24) });
  assert.equal(monday.sections.find((s) => s.id === 'self_awareness'), undefined);
  // 换成周一复盘就出现
  const mondayReview = buildContextEnvelope({ state: scanned.state, sessionId: 's1', now: at(121 + 24), awarenessReviewWeekday: 1 });
  assert.ok(mondayReview.sections.find((s) => s.id === 'self_awareness'));
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
