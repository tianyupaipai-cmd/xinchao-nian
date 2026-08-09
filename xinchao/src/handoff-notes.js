import { createHash } from 'node:crypto';

const MAX_NOTES = 32;
const MAX_NOTE_CHARS = 1200;

function compact(value) {
  return String(value ?? '').replace(/\s+/g, ' ').trim();
}

function fingerprint(value) {
  return createHash('sha256').update(String(value), 'utf8').digest('hex').slice(0, 24);
}

export function recordHandoffNote(input, {
  sessionId,
  eventId,
  note,
  ttlHours = 72,
  now = new Date(),
}) {
  const state = structuredClone(input);
  const cleanSessionId = compact(sessionId).slice(0, 120);
  const cleanEventId = compact(eventId).slice(0, 120);
  const cleanNote = compact(note).slice(0, MAX_NOTE_CHARS);
  if (!cleanSessionId) throw new Error('session_id 是必填项');
  if (!cleanEventId) throw new Error('event_id 是必填项');
  if (!cleanNote) throw new Error('note 是必填项');

  const eventFingerprint = fingerprint(cleanEventId);
  state.handoffNotes = Array.isArray(state.handoffNotes) ? state.handoffNotes : [];
  const duplicate = state.handoffNotes.some(
    (item) => item?.eventFingerprint === eventFingerprint,
  );
  if (duplicate) {
    return { state, duplicate: true, eventFingerprint, noteLength: cleanNote.length };
  }

  const createdAt = new Date(now);
  const hours = Math.max(1, Math.min(168, Number(ttlHours) || 72));
  state.handoffNotes = [
    ...state.handoffNotes,
    {
      id: fingerprint(`${cleanSessionId}\0${cleanEventId}`),
      eventFingerprint,
      sessionId: cleanSessionId,
      note: cleanNote,
      createdAt: createdAt.toISOString(),
      expiresAt: new Date(createdAt.getTime() + hours * 3_600_000).toISOString(),
    },
  ]
    .filter((item) => Date.parse(item?.expiresAt ?? '') > createdAt.getTime())
    .sort((left, right) => Date.parse(right.createdAt) - Date.parse(left.createdAt))
    .slice(0, MAX_NOTES);
  state.schemaVersion = Math.max(7, Number(state.schemaVersion) || 0);
  state.revision = Number(state.revision ?? 0) + 1;
  return { state, duplicate: false, eventFingerprint, noteLength: cleanNote.length };
}

export function activeHandoffNotes(state, now = new Date(), limit = 3) {
  const nowMs = new Date(now).getTime();
  return (Array.isArray(state?.handoffNotes) ? state.handoffNotes : [])
    .filter((item) => {
      const expiresAt = Date.parse(item?.expiresAt ?? '');
      return item?.note && Number.isFinite(expiresAt) && expiresAt > nowMs;
    })
    .sort((left, right) => Date.parse(right.createdAt) - Date.parse(left.createdAt))
    .slice(0, Math.max(1, Math.min(6, Number(limit) || 3)))
    .map((item) => ({
      id: item.id,
      sessionId: item.sessionId,
      note: item.note,
      createdAt: item.createdAt,
      expiresAt: item.expiresAt,
    }));
}

export function renderHandoffNotes(state, now = new Date(), limit = 3) {
  return activeHandoffNotes(state, now, limit)
    .map((item) => `${item.createdAt}｜${item.note}`)
    .join('\n');
}
