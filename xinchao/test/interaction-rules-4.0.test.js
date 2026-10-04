import assert from 'node:assert/strict';
import test from 'node:test';
import { guardTag, loadInteractionRules, splitExchange } from '../src/interaction-rules.js';

const R = loadInteractionRules(null);
const tag = (o) => ({ tone: 'warm', warmth: 0.6, tension: 0.1, sub: null, strength: null, closeness: null, who: null, ...o });

test('拆 exchange：认「她说/他回」，没写就整段当她说的', () => {
  assert.deepEqual(splitExchange('她说：今天好累 他回：抱抱'), { her: '今天好累', his: '抱抱' });
  assert.equal(splitExchange('今天好累').her, '今天好累');
});

test('和好要真吵过、而且不是问句', () => {
  assert.equal(guardTag(tag({ type: 'reconciliation' }), '不气了', { rules: R, hasGrudge: false }).type, 'affection');
  assert.equal(guardTag(tag({ type: 'reconciliation' }), '你还生气吗', { rules: R, hasGrudge: true }).type, 'affection');
  assert.equal(guardTag(tag({ type: 'reconciliation' }), '好啦我不气了', { rules: R, hasGrudge: true }).type, 'reconciliation');
});

test('心疼她本人要她真的难受；编的不算', () => {
  assert.equal(guardTag(tag({ type: 'empathy', sub: '心疼', closeness: 'her' }), '今天天气不错', { rules: R }).type, 'companionship');
  assert.equal(guardTag(tag({ type: 'empathy', sub: '心疼', closeness: 'her' }), '我发烧了好难受', { rules: R }).type, 'empathy');
  assert.equal(guardTag(tag({ type: 'empathy', sub: '心疼', closeness: 'stranger', who: '主角' }), '这部电视剧里的主角好惨', { rules: R }).type, 'companionship');
});

test('远近名单说了算（配置里写的名字）', () => {
  const custom = { ...R, closeness: { 妈妈: 'family' } };
  assert.equal(guardTag(tag({ type: 'empathy', sub: '心疼', closeness: 'stranger', who: '她妈妈' }), '我妈妈住院了', { rules: custom }).closeness, 'family');
});

test('吃醋要有细项；她说我忘了是被忘，他忘了是自责', () => {
  assert.equal(guardTag(tag({ type: 'slighted', sub: null }), '你看他好帅', { rules: R }).type, 'companionship');
  assert.equal(guardTag(tag({ type: 'loss', sub: '失落' }), '啊我忘了今天要陪你', { rules: R }).sub, '被忘');
  assert.equal(guardTag(tag({ type: 'slighted', sub: '被忘' }), '你是不是忘了答应我的', { rules: R }).sub, '自责');
});

test('心动分轻重、害羞用原话补认', () => {
  assert.equal(guardTag(tag({ type: 'affection', strength: 'light' }), '我好想你了', { rules: R }).strength, 'heavy');
  assert.equal(guardTag(tag({ type: 'affection', strength: 'heavy' }), '亲亲', { rules: R }).strength, 'light');
  assert.equal(guardTag(tag({ type: 'affection' }), '你是不是脸红了', { rules: R }).sub, '害羞');
});

test('刚亲近完一句不太紧的嫌弃当撒娇；日常告别不算失落', () => {
  const recent = [{ type: 'affection', at: Date.now() - 60_000 }];
  assert.equal(guardTag(tag({ type: 'conflict', tension: 0.3 }), '烦人', { rules: R, recent }).type, 'affection');
  assert.equal(guardTag(tag({ type: 'conflict', tension: 0.8 }), '滚', { rules: R, recent }).type, 'conflict');
  assert.equal(guardTag(tag({ type: 'loss', sub: '分别' }), '晚安啦', { rules: R }).type, 'companionship');
});
