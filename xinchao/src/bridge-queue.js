import { randomUUID } from 'node:crypto';
import { StateStore } from './state-store.js';

export const BRIDGE_SERVER_PROTOCOL = 'xinchao-bridge-server/1';
export const BRIDGE_STREAM_PROTOCOL = 'xinchao-bridge-stream/1';
export const BRIDGE_RUNTIME_PROTOCOL = 'xinchao-runtime-wake/1';
export const BRIDGE_REASONS = Object.freeze(['user_interaction', 'user_note', 'scheduled_interaction', 'user_feedback']);

const DELIVERY_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{5,159}$/;

function compact(value, maxLength) {
  return String(value ?? '').replace(/\s+/g, ' ').trim().slice(0, maxLength);
}

function initialQueue() {
  return { schemaVersion: 1, deliveries: [] };
}

export class BridgeQueue {
  constructor(path, { maxEntries = 500, ttlHours = 168 } = {}) {
    this.store = new StateStore(path, initialQueue);
    this.maxEntries = maxEntries;
    this.ttlHours = ttlHours;
  }

  async init() {
    await this.store.read();
  }

  async enqueue({ eventId, reason, message, deliverAfter = null }, now = new Date()) {
    const dedupeKey = compact(eventId, 120);
    const safeReason = compact(reason, 128);
    const safeMessage = compact(message, 4096);
    if (dedupeKey.length < 8) throw new Error('bridge event_id must contain at least 8 characters');
    if (!BRIDGE_REASONS.includes(safeReason)) throw new Error('bridge accepts user interactions only');
    if (!safeMessage) throw new Error('bridge message is required');
    const dueAt = deliverAfter ? new Date(deliverAfter) : now;
    if (!Number.isFinite(dueAt.getTime())) throw new Error('deliver_after must be an ISO timestamp');
    const expiresAt = new Date(Math.max(now.getTime(), dueAt.getTime()) + this.ttlHours * 3_600_000);
    let result;
    await this.store.update((queue) => {
      queue.schemaVersion = 1;
      queue.deliveries = Array.isArray(queue.deliveries) ? queue.deliveries : [];
      const existing = queue.deliveries.find((item) => item.eventId === dedupeKey);
      if (existing) {
        result = { delivery: existing, duplicate: true };
        return queue;
      }
      const delivery = {
        id: `delivery-${randomUUID()}`,
        eventId: dedupeKey,
        reason: safeReason,
        message: safeMessage,
        status: 'pending',
        createdAt: now.toISOString(),
        deliverAfter: dueAt.toISOString(),
        expiresAt: expiresAt.toISOString(),
        attempts: 0,
        deliveredAt: null,
        lastFailureCode: null,
      };
      queue.deliveries.push(delivery);
      queue.deliveries = queue.deliveries
        .filter((item) => item.status === 'pending' || Date.parse(item.deliveredAt || item.createdAt) > now.getTime() - 30 * 86_400_000)
        .slice(-this.maxEntries);
      result = { delivery, duplicate: false };
      return queue;
    });
    return structuredClone(result);
  }

  async ready(now = new Date()) {
    const queue = await this.store.read();
    return queue.deliveries.filter((item) => (
      item.status === 'pending'
      && Date.parse(item.deliverAfter) <= now.getTime()
      && Date.parse(item.expiresAt) > now.getTime()
    ));
  }

  async get(id, now = new Date()) {
    if (!DELIVERY_ID.test(String(id))) return null;
    const item = (await this.store.read()).deliveries.find((delivery) => delivery.id === id);
    if (!item || item.status !== 'pending' || Date.parse(item.expiresAt) <= now.getTime()) return null;
    return {
      protocol: BRIDGE_RUNTIME_PROTOCOL,
      deliveryId: item.id,
      reason: item.reason,
      message: item.message,
    };
  }

  async acknowledge(id, status, code = '', now = new Date()) {
    let result = null;
    await this.store.update((queue) => {
      const item = queue.deliveries.find((delivery) => delivery.id === id);
      if (!item) return queue;
      if (status === 'delivered') {
        item.status = 'delivered';
        item.deliveredAt ??= now.toISOString();
        item.lastFailureCode = null;
      } else if (status === 'retryable_failed') {
        if (item.status !== 'delivered') item.status = 'pending';
        item.attempts = Number(item.attempts || 0) + 1;
        item.lastFailureCode = compact(code || 'runtime_failed', 80);
      } else {
        throw new Error('unsupported bridge acknowledgement status');
      }
      result = structuredClone(item);
      return queue;
    });
    return result;
  }

  async list({ limit = 30 } = {}) {
    const queue = await this.store.read();
    return queue.deliveries.slice(-Math.max(1, Math.min(100, Number(limit) || 30))).reverse();
  }
}
