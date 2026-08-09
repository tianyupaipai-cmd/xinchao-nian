import { barkDuplicateCheck, recentBarkHistory } from './engine.js';

export async function selectUniqueBark({ state, generate, maxAttempts = 2, onRejected = null }) {
  const recentMessages = recentBarkHistory(state);
  let rejectedMessage = null;
  let lastCandidate = null;
  const attemptsAllowed = Math.max(1, Math.min(2, Number(maxAttempts) || 2));

  for (let attempt = 1; attempt <= attemptsAllowed; attempt += 1) {
    const candidate = await generate({ recentMessages, rejectedMessage });
    const message = typeof candidate === 'string' ? candidate : candidate?.message;
    if (candidate?.send === false || !message) {
      return { message: '', candidate, reason: 'empty', attempts: attempt };
    }

    lastCandidate = candidate;
    const check = barkDuplicateCheck(message, state);
    if (!check.duplicate) return { message, candidate, reason: null, attempts: attempt };
    if (onRejected) await onRejected({ attempt, similarity: check.similarity });
    rejectedMessage = message;
  }

  return { message: '', candidate: lastCandidate, reason: 'duplicate', attempts: attemptsAllowed };
}
