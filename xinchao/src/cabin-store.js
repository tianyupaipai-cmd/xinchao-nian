import { randomUUID } from 'node:crypto';
import { StateStore } from './state-store.js';

function initialCabin() {
  return { schemaVersion: 1, notes: [], ledger: [] };
}

function text(value, name, max = 100_000) {
  const result = String(value ?? '').trim();
  if (!result) throw new Error(`${name} is required`);
  if (result.length > max) throw new Error(`${name} is too large`);
  return result;
}

function eventId(value) {
  const result = text(value, 'event_id', 120);
  if (result.length < 8) throw new Error('event_id must contain 8 to 120 characters');
  return result;
}

function iso(value, fallback = new Date()) {
  const date = value ? new Date(value) : fallback;
  if (!Number.isFinite(date.getTime())) throw new Error('timestamp must be a valid ISO date');
  return date.toISOString();
}

function money(value) {
  const amount = Number(value);
  if (!Number.isFinite(amount) || amount < 0) throw new Error('amount must be a non-negative number');
  return Math.round((amount + Number.EPSILON) * 100) / 100;
}

function normalize(state) {
  state.schemaVersion = 1;
  state.notes = Array.isArray(state.notes) ? state.notes : [];
  state.ledger = Array.isArray(state.ledger) ? state.ledger : [];
  return state;
}

function totals(entries) {
  const expense = entries.filter((entry) => entry.type === 'expense').reduce((sum, entry) => sum + Number(entry.amount || 0), 0);
  const income = entries.filter((entry) => entry.type === 'income').reduce((sum, entry) => sum + Number(entry.amount || 0), 0);
  return {
    expense: Math.round(expense * 100) / 100,
    income: Math.round(income * 100) / 100,
    net: Math.round((expense - income) * 100) / 100,
  };
}

export class CabinStore {
  constructor(path, { maxNotes = 2000, maxLedgerEntries = 5000 } = {}) {
    this.store = new StateStore(path, initialCabin);
    this.maxNotes = maxNotes;
    this.maxLedgerEntries = maxLedgerEntries;
  }

  async init() {
    await this.store.read();
  }

  async snapshot() {
    const state = normalize(await this.store.read());
    const notes = [...state.notes].sort((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt));
    const ledger = [...state.ledger].sort((a, b) => Date.parse(b.date) - Date.parse(a.date) || Date.parse(b.createdAt) - Date.parse(a.createdAt));
    return {
      schemaVersion: 1,
      generatedAt: new Date().toISOString(),
      notes,
      ledger,
      unreadAiNotes: notes.filter((note) => note.from === 'ai' && !note.readAt).length,
      totals: totals(ledger),
    };
  }

  async addNote(input, now = new Date()) {
    const from = String(input.from ?? '').trim().toLowerCase();
    if (!['user', 'ai'].includes(from)) throw new Error('from must be user or ai');
    const dedupe = eventId(input.eventId ?? input.event_id);
    const content = text(input.content, 'content');
    const createdAt = iso(input.timestamp, now);
    const locked = from === 'user' ? input.locked !== false : false;
    let result;
    await this.store.update((raw) => {
      const state = normalize(raw);
      const existing = state.notes.find((note) => note.eventId === dedupe);
      if (existing) {
        result = { note: existing, duplicate: true };
        return state;
      }
      const note = {
        id: `note-${randomUUID()}`,
        eventId: dedupe,
        from,
        content,
        locked,
        unlockedAt: locked ? null : createdAt,
        createdAt,
        readAt: from === 'ai' ? null : createdAt,
      };
      state.notes.push(note);
      state.notes = state.notes.slice(-this.maxNotes);
      result = { note, duplicate: false };
      return state;
    });
    return structuredClone(result);
  }

  async setNoteLock(id, locked, now = new Date()) {
    let result = null;
    await this.store.update((raw) => {
      const state = normalize(raw);
      const note = state.notes.find((entry) => entry.id === String(id));
      if (!note || note.from !== 'user') return state;
      note.locked = Boolean(locked);
      note.unlockedAt = note.locked ? null : (note.unlockedAt ?? now.toISOString());
      result = structuredClone(note);
      return state;
    });
    return result;
  }

  async markAiNotesRead(ids = null, now = new Date()) {
    const wanted = Array.isArray(ids) ? new Set(ids.map(String)) : null;
    let changed = 0;
    await this.store.update((raw) => {
      const state = normalize(raw);
      for (const note of state.notes) {
        if (note.from !== 'ai' || note.readAt || (wanted && !wanted.has(note.id))) continue;
        note.readAt = now.toISOString();
        changed += 1;
      }
      return state;
    });
    return { changed };
  }

  async unlockedUserNotes() {
    const state = normalize(await this.store.read());
    return state.notes
      .filter((note) => note.from === 'user' && !note.locked)
      .sort((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt))
      .map(({ id, content, createdAt, unlockedAt }) => ({ id, content, createdAt, unlockedAt }));
  }

  async addLedger(input, now = new Date()) {
    const type = String(input.type ?? '').trim().toLowerCase();
    if (!['expense', 'income'].includes(type)) throw new Error('type must be expense or income');
    const dedupe = eventId(input.eventId ?? input.event_id);
    const createdAt = now.toISOString();
    let result;
    await this.store.update((raw) => {
      const state = normalize(raw);
      const existing = state.ledger.find((entry) => entry.eventId === dedupe);
      if (existing) {
        result = { entry: existing, duplicate: true };
        return state;
      }
      const entry = {
        id: `ledger-${randomUUID()}`,
        eventId: dedupe,
        type,
        item: text(input.item, 'item', 500),
        amount: money(input.amount),
        date: iso(input.date, now).slice(0, 10),
        createdAt,
        updatedAt: createdAt,
      };
      state.ledger.push(entry);
      state.ledger = state.ledger.slice(-this.maxLedgerEntries);
      result = { entry, duplicate: false };
      return state;
    });
    return structuredClone(result);
  }

  async updateLedger(id, patch, now = new Date()) {
    let result = null;
    await this.store.update((raw) => {
      const state = normalize(raw);
      const entry = state.ledger.find((item) => item.id === String(id));
      if (!entry) return state;
      if (patch.type !== undefined) {
        const type = String(patch.type).trim().toLowerCase();
        if (!['expense', 'income'].includes(type)) throw new Error('type must be expense or income');
        entry.type = type;
      }
      if (patch.item !== undefined) entry.item = text(patch.item, 'item', 500);
      if (patch.amount !== undefined) entry.amount = money(patch.amount);
      if (patch.date !== undefined) entry.date = iso(patch.date, now).slice(0, 10);
      entry.updatedAt = now.toISOString();
      result = structuredClone(entry);
      return state;
    });
    return result;
  }

  async deleteLedger(id) {
    let result = null;
    await this.store.update((raw) => {
      const state = normalize(raw);
      const index = state.ledger.findIndex((item) => item.id === String(id));
      if (index < 0) return state;
      [result] = state.ledger.splice(index, 1);
      return state;
    });
    return result ? structuredClone(result) : null;
  }
}
