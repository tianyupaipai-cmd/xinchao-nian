// 【记忆（OB）】读 OB 的心跳文件，判断记忆服务还活着没有。
// 代码地图见 src/README.md。

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
