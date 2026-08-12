import assert from 'node:assert/strict';
import test from 'node:test';

import { parseMemoryMapText, parseMemoryPreviewText } from '../src/ombre-client.js';

test('pulse text becomes a metadata-only memory map', () => {
  const result = parseMemoryMapText(`
固化桶：1
动态桶：2
归档桶：3
总占用：2.5 MB
📌 [a35f6a3aeb35] 《以前我们只有文字》 主题:恋爱,成长 情感:V0.9/A0.7 重要:10 权重:80 标签:共同记忆,承诺,成长
[c3b4466ae887] 《你呼吸就可以想起来了》 主题:恋爱 情感:V0.8/A0.4 重要:8 权重:45 标签:共同记忆,承诺,成长
[d4c5577bf998] 《一段完全不同的生活记忆》 主题:生活 情感:V0.5/A0.2 重要:4 权重:12 标签:吃饭,天气,通勤
[e5d6688ca009] 《另一段独立的工作记录》 主题:工作 情感:V0.4/A0.5 重要:3 权重:9 标签:项目,会议,进度
`);

  assert.equal(result.available, true);
  assert.equal(result.total, 4);
  assert.equal(result.stats.pinned, 1);
  assert.equal(result.stars[0].pinned, true);
  assert.equal(result.stars[0].driveSnapshot, null);
  assert.equal(result.stars[0].historical, true);
  assert.equal(result.edges.length, 1);
  assert.equal(result.edges[0].kind, 'tag-derived');
  assert.equal('content' in result.stars[0], false);
});

test('structured 3.0 map preserves optional emotional stamp fields', () => {
  const result = parseMemoryMapText(JSON.stringify({
    schemaVersion: 3,
    stars: [{
      id: 'future-bucket',
      title: '带情感戳的瞬间',
      domain: ['恋爱'],
      importance: 9,
      valence: .72,
      arousal: .84,
      drive_snapshot: { possess: .8 },
      drive_affinity: { possess: .9 },
      created_at: '2026-08-09T10:00:00.000Z',
    }],
    edges: [],
  }));

  assert.equal(result.available, true);
  assert.equal(result.stars[0].historical, false);
  assert.deepEqual(result.stars[0].driveSnapshot, { possess: .8 });
  assert.deepEqual(result.stars[0].driveAffinity, { possess: .9 });
  assert.equal(result.capabilities.driveSnapshots, true);
  assert.equal(result.capabilities.driveAffinity, true);
  assert.equal(result.capabilities.timestamps, true);
});

test('bucket preview preserves original lines but never returns more than seven', () => {
  const source = Array.from({ length: 10 }, (_, index) => `原文第 ${index + 1} 行`).join('\n');
  const result = parseMemoryPreviewText(JSON.stringify({ ok: true, id: 'bucket-1', preview: source, truncated: true }), 'bucket-1');
  assert.equal(result.available, true);
  assert.equal(result.lineCount, 7);
  assert.equal(result.preview.split('\n').at(-1), '原文第 7 行');
  assert.equal(result.truncated, true);
});

test('bucket preview refuses a mismatched bucket id', () => {
  const result = parseMemoryPreviewText(JSON.stringify({ ok: true, id: 'other', preview: '不该返回' }), 'wanted');
  assert.equal(result.available, false);
  assert.equal(result.reason, 'id_mismatch');
  assert.equal(result.preview, '');
});
