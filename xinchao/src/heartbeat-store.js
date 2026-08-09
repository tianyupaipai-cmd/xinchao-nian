import { readFile } from 'node:fs/promises';

/** Read the content-free timestamp written by Ombre's POST /heartbeat route. */
export async function readOmbreHeartbeat(filePath) {
  try {
    const raw = await readFile(filePath, 'utf8');
    const value = JSON.parse(raw);
    const at = new Date(value.recordedAt ?? value.recorded_at ?? '');
    return Number.isFinite(at.getTime()) ? at : null;
  } catch (error) {
    if (error?.code === 'ENOENT') return null;
    throw error;
  }
}
