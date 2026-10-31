import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { NowLines, validateNowLine } from '../src/now-lines.js';
import { buildNowCompact } from '../src/context-envelope.js';
import { newState } from '../src/engine.js';

const T = new Date('2026-10-26T06:00:00Z');
const SECRET = '外接测试句子ZX';

test('外接一行：校验——一行、60 字内、不带小数和驱力 key、minutes 1–180、来源名', () => {
  assert.ok(validateNowLine({ source: 'a', text: 'x', minutes: 0 }).error);
  assert.ok(validateNowLine({ source: 'a', text: 'x', minutes: 181 }).error);
  assert.ok(validateNowLine({ source: '', text: 'x', minutes: 5 }).error);
  assert.ok(validateNowLine({ source: 'a b', text: 'x', minutes: 5 }).error);
  assert.ok(validateNowLine({ source: 'a', text: '两行\n第二行', minutes: 5 }).error);
  assert.ok(validateNowLine({ source: 'a', text: '有 0.8 小数', minutes: 5 }).error);
  assert.ok(validateNowLine({ source: 'a', text: 'libido 字样', minutes: 5 }).error);
  assert.ok(validateNowLine({ source: 'a', text: '长'.repeat(61), minutes: 5 }).error);
  assert.deepEqual(validateNowLine({ source: '外接', text: '【外接】一句', minutes: 15 }), { source: '外接', text: '【外接】一句', minutes: 15, priority: 3 });
  assert.ok(validateNowLine({ source: 'a', text: 'x', minutes: 5, priority: 0 }).error);
  assert.ok(validateNowLine({ source: 'a', text: 'x', minutes: 5, priority: 6 }).error);
  assert.ok(validateNowLine({ source: 'a', text: 'x', minutes: 5, priority: 2.5 }).error);
  assert.equal(validateNowLine({ source: 'a', text: 'x', minutes: 5, priority: '1' }).priority, 1);
});

test('外接一行：同来源覆盖、最多 3 个来源、到期自动没了、GET 不回内容', () => {
  const n = new NowLines();
  const t0 = T.getTime();
  assert.ok(!n.set({ source: 'a', text: '甲', minutes: 1 }, t0).error);
  n.set({ source: 'a', text: '甲二', minutes: 10 }, t0);
  n.set({ source: 'b', text: '乙', minutes: 10 }, t0 + 1);
  n.set({ source: 'c', text: '丙', minutes: 10 }, t0 + 2);
  assert.equal(n.set({ source: 'd', text: '丁', minutes: 10 }, t0 + 3).status, 409);
  assert.deepEqual(n.texts(t0 + 5), ['甲二', '乙', '丙']);
  assert.deepEqual(n.texts(t0 + 11 * 60_000), []);
  n.set({ source: 'e', text: SECRET, minutes: 10 }, t0);
  assert.ok(!JSON.stringify(n.sources(t0)).includes(SECRET));
  assert.ok(n.remove('e'));
  assert.deepEqual(n.texts(t0), []);
});

test('外接一行 4.3 优先级：满了挤掉最不要紧的；一样要紧不挤；此刻里要紧的在前', () => {
  const n = new NowLines();
  const t0 = T.getTime();
  n.set({ source: '天气', text: '外面下雨', minutes: 30, priority: 4 }, t0);
  n.set({ source: '余温', text: '刚看完一集', minutes: 30 }, t0 + 1);          // 默认 3
  n.set({ source: '脉', text: '心跳偏快', minutes: 30, priority: 4 }, t0 + 2);
  assert.deepEqual(n.texts(t0 + 3), ['刚看完一集', '外面下雨', '心跳偏快']);   // 3 在前，两个 4 按先挂
  const r = n.set({ source: '盼头', text: '约了九点', minutes: 30, priority: 2 }, t0 + 4);
  assert.equal(r.evicted, '天气');                                              // 两个 4 里挤最早挂的
  assert.deepEqual(n.texts(t0 + 5), ['约了九点', '刚看完一集', '心跳偏快']);
  assert.equal(n.set({ source: '环境', text: '深夜', minutes: 30, priority: 4 }, t0 + 6).status, 409);   // 不比最不要紧的更要紧
  assert.equal(n.set({ source: '别的', text: '也是三', minutes: 30 }, t0 + 7).evicted, '脉');           // 默认 3 比剩下的 4 要紧，挤掉它
  assert.equal(n.set({ source: '再一个', text: '还是三', minutes: 30 }, t0 + 8).status, 409);            // 剩下都是 2、3，一样要紧不挤
});

test('外接一行：排在身体下面；块满了外接的先让位，不让整块被拦', () => {
  const s = newState(T);
  const out = buildNowCompact(s, T, { body: '身体：心跳 70，呼吸平稳', extra: ['【外接】一句'] });
  assert.ok(out.ok);
  const lines = out.text.split('\n');
  assert.equal(lines.indexOf('【外接】一句'), lines.indexOf('身体：心跳 70，呼吸平稳') + 1);
  const crowded = buildNowCompact(s, T, { body: '身体：心跳 70，呼吸平稳', extra: ['一'.repeat(60), '二'.repeat(60), '三'.repeat(60), '四'.repeat(60), '五'.repeat(60), '六'.repeat(60), '七'.repeat(60)] });
  assert.ok(crowded.ok && crowded.lines <= 8 && crowded.text.length <= 400);
});

test('外接一行：挂的内容不出现在任何别的出口（只有 GET /v1/now 读它）', async () => {
  // 1) 其它出口的构建函数根本不接收它
  const s = newState(T);
  assert.ok(!buildNowCompact(s, T).text.includes(SECRET));   // 不传 extra（比如相关度小模型那路 nowText）就没有
  // 2) server.js 里读挂的内容（texts）只有一处，而且在 /v1/now 那个路由里；没有任何地方把它写进状态或日志
  const src = readFileSync(new URL('../src/server.js', import.meta.url), 'utf8');
  const uses = src.split('nowLines.texts(').length - 1;
  assert.equal(uses, 1);
  const at = src.indexOf('nowLines.texts(');
  const route = src.lastIndexOf("url.pathname === '/v1/now'", at);
  assert.ok(route > 0 && !src.slice(route + 30, at).includes('url.pathname ==='), '读外接行的地方必须在 /v1/now 路由里');
  assert.ok(!/log\([^)]*text/.test(src.slice(src.indexOf("'/v1/now-lines'"), src.indexOf("'/v1/now-lines'") + 900)), '日志不记内容');
  // 3) 其它模块（看板、推送、桥、记忆客户端……）一个都不引用 now-lines
  for (const f of ['dashboard-projection.js', 'bark-client.js', 'bridge-queue.js', 'ombre-client.js', 'relevance-shadow.js', 'engine.js', 'state-store.js']) {
    assert.ok(!readFileSync(new URL(`../src/${f}`, import.meta.url), 'utf8').includes('now-lines'), f);
  }
  // 4) 模块本身不碰文件
  const mod = readFileSync(new URL('../src/now-lines.js', import.meta.url), 'utf8');
  assert.ok(!/node:fs|writeFile|readFile/.test(mod));
});

test('/v1/drives：只给短名、档位、满足没有、念头罐那句，不给小数', () => {
  const src = readFileSync(new URL('../src/server.js', import.meta.url), 'utf8');
  const at = src.indexOf("url.pathname === '/v1/drives'");
  const block = src.slice(at, src.indexOf("return send(response, 200, { drives", at));
  assert.ok(at > 0 && !/value:|Number\(state\?\.drives\?\.\[key\]\)\s*[,}]/.test(block.replace('driveLevel(key, Number(state?.drives?.[key])', '')));
});
