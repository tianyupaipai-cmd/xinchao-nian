import assert from 'node:assert/strict';
import test from 'node:test';

import { newState, settleState } from '../src/engine.js';
import { emotionGrowthFactor, EMOTION_BASELINE } from '../src/emotion.js';

const T0 = '2026-09-05T08:00:00.000Z';
const T1 = '2026-09-05T10:00:00.000Z';
function baseState() {
  const state = newState(new Date(T0));
  state.lastSettledAt = T0;
  state.lastConversationAt = T0;
  state.drives = Object.fromEntries(Object.keys(state.drives).map((key) => [key, 0.15]));
  return state;
}
function withEmotion(valence, arousal) {
  const state = baseState();
  state.emotion.valence = valence;
  state.emotion.arousal = arousal;
  return state;
}

test('neutral emotion leaves growth untouched (factor 1)', () => {
  assert.equal(emotionGrowthFactor('monitor', { valence: 0.5, arousal: EMOTION_BASELINE.arousal }), 1);
  assert.equal(emotionGrowthFactor('grieve', { valence: 0.1, arousal: 0.9 }), 1);
  assert.equal(emotionGrowthFactor('monitor', null), 1);
});

test('low valence speeds up monitor/crave and slows share; high valence does the reverse', () => {
  const sad = settleState(withEmotion(0.2, 0.3), new Date(T1)).state;
  const happy = settleState(withEmotion(0.85, 0.3), new Date(T1)).state;
  const neutral = settleState(withEmotion(0.5, EMOTION_BASELINE.arousal), new Date(T1)).state;
  assert.ok(sad.drives.monitor > neutral.drives.monitor && neutral.drives.monitor > happy.drives.monitor);
  assert.ok(sad.drives.crave > neutral.drives.crave);
  assert.ok(happy.drives.share > neutral.drives.share && neutral.drives.share > sad.drives.share);
});

test('high arousal speeds monitor and damps boredom/reflection', () => {
  const wired = settleState(withEmotion(0.5, 0.9), new Date(T1)).state;
  const neutral = settleState(withEmotion(0.5, EMOTION_BASELINE.arousal), new Date(T1)).state;
  assert.ok(wired.drives.monitor > neutral.drives.monitor);
  assert.ok(wired.drives.boredom < neutral.drives.boredom);
  assert.ok(wired.drives.reflection < neutral.drives.reflection);
});

test('modulation stays inside its clamp and can be switched off', () => {
  assert.ok(emotionGrowthFactor('monitor', { valence: 0, arousal: 1 }) <= 1.8);
  assert.ok(emotionGrowthFactor('boredom', { valence: 0, arousal: 1 }) >= 0.4);
  const off = settleState(withEmotion(0.2, 0.3), new Date(T1), 90, { emotionModulationEnabled: false }).state;
  const neutral = settleState(withEmotion(0.5, EMOTION_BASELINE.arousal), new Date(T1), 90, { emotionModulationEnabled: false }).state;
  assert.equal(off.drives.monitor, neutral.drives.monitor);
});

test('a sad emotion never pushes a drive above its resting ceiling', () => {
  let state = withEmotion(0.1, 0.9);
  for (let hour = 1; hour <= 48; hour += 1) {
    state.emotion.valence = 0.1; state.emotion.arousal = 0.9;
    state = settleState(state, new Date(Date.parse(T0) + hour * 3_600_000)).state;
  }
  assert.ok(state.drives.monitor <= 0.78 + 1e-9);
});
