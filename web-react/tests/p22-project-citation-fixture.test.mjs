import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { findFixtureKnowledgeEvidence, groundedFixtureKnowledgeReply } from '../e2e/knowledge-fixture-evidence.mjs';

const projectMarker = 'AGENTMESH_V41_PROJECT_1789984513137';
const globalMarker = 'AGENTMESH_V41_GLOBAL_1789983319357';
function context({
  marker = projectMarker, citationId = 3, available = '[1] [3]',
  text = `当前项目的测试标记是 ${marker}。`,
  identityId = citationId, prefix = '[Current Task]\n请根据当前项目资料回答。\n\n',
  suffix = '',
} = {}) {
  return `${prefix}[Retrieved Knowledge]\n` +
    `[Evidence 1]\n[1] source=other.txt; score=0.98\ncitation=[1]\ndocument_id=chunk-other\nsource=other.txt\n\n其他资料：无关。\n\n` +
    `[Evidence ${citationId}]\n[${citationId}] source=project.txt; score=0.97\ncitation=[${identityId}]\ndocument_id=chunk-project\nsource=project.txt\n\n${text}` +
    `\n\n[Citation Policy]\navailable_citations=${available}\nCitation policy:\n- Use exact citations.\n${suffix}`;
}

const find = (messages, kind = 'PROJECT') => findFixtureKnowledgeEvidence(messages, kind);

test('project answer gets its own evidence citation rather than guessing [1]', () => {
  assert.deepEqual(find([{ role: 'user', content: context() }]), {
    marker: projectMarker, citationId: 3,
  });
});

test('Global positive derives the local citation from actual Global evidence', () => {
  assert.deepEqual(find([{
    role: 'user', content: context({ marker: globalMarker, text: `用户 A 的测试标记是 ${globalMarker}。` }),
  }], 'GLOBAL'), { marker: globalMarker, citationId: 3 });
});

test('the question, conversation history, and generic citations cannot fabricate evidence', () => {
  assert.equal(find([{
    role: 'user', content: `[Current Task]\n${projectMarker}\n\n[Conversation Memory]\nuser: ${projectMarker} [1]`,
  }]), null);
  assert.equal(find([{
    role: 'user', content: context({ marker: projectMarker, text: '其他资料：没有标记。', prefix: `[Current Task]\n${projectMarker}\n\n` }),
  }]), null);
});

test('no authorization / retrieval block is not treated as a grounded answer', () => {
  assert.equal(find([{ role: 'user', content: `[Current Task]\n项目标记是什么？\n\n[Citation Policy]\navailable_citations=[1]` }]), null);
  assert.equal(find([{ role: 'user', content: `[Retrieved Knowledge]\n${projectMarker}` }]), null);
});

test('mismatched identity, absent allowed ID, and absent stable document identity fail closed', () => {
  assert.equal(find([{ role: 'user', content: context({ identityId: 1 }) }]), null);
  assert.equal(find([{ role: 'user', content: context({ available: '[1]' }) }]), null);
  assert.equal(find([{ role: 'user', content: context().replace('document_id=chunk-project', 'no_document_id=chunk-project') }]), null);
});

test('metadata markers do not count as knowledge text and wrong knowledge scope cannot match', () => {
  const markerOnlyInIdentity = context({ text: '没有测试标记。' }).replace('source=project.txt', `source=${projectMarker}.txt`);
  assert.equal(find([{ role: 'user', content: markerOnlyInIdentity }]), null);
  assert.equal(find([{ role: 'user', content: context() }], 'GLOBAL'), null);
  assert.equal(find([{ role: 'user', content: context() }], 'ALL'), null);
});

test('an unrelated earlier model message cannot supply a knowledge marker', () => {
  assert.equal(find([
    { role: 'assistant', content: `模型以前说 ${projectMarker} [3]` },
    { role: 'user', content: '请问当前项目标记是什么？' },
  ]), null);
});

test('browser fixture does not hardcode [1], bypass citation guard, or weaken project isolation', () => {
  const source = readFileSync(new URL('../e2e/v4-1-browser-e2e.mjs', import.meta.url), 'utf8');
  assert.match(source, /groundedFixtureKnowledgeReply\(messages\)/);
  assert.match(source, /PROJECT citation guard must pass/);
  assert.match(source, /PROJECT Knowledge had no projected used citations/);
  assert.match(source, /unbound GLOBAL Knowledge leaked into PROJECT conversation/);
  assert.doesNotMatch(source, /if \(projectMarker\) return/);
  assert.doesNotMatch(source, /if \(globalMarker\) return/);
});


test('actual browser fixture reply contains correct citation and refuses unsupported marker', () => {
  assert.deepEqual(groundedFixtureKnowledgeReply([{ role: 'user', content: context() }]), {
    content: `根据当前项目资料，项目测试标记是 ${projectMarker} [3]。`,
  });
  assert.deepEqual(groundedFixtureKnowledgeReply([{ role: 'user', content: context({ marker: globalMarker, text: `用户 A 的测试标记是 ${globalMarker}。` }) }]), {
    content: `根据当前可用资料，测试标记是 ${globalMarker} [3]。`,
  });
  assert.equal(groundedFixtureKnowledgeReply([{ role: 'user', content: context({ available: '[1]' }) }]), null);
  assert.equal(groundedFixtureKnowledgeReply([{ role: 'user', content: `[Current Task]\n${projectMarker}` }]), null);
});

test('real OpenAI-compatible multimodal message content is parsed from text parts only', () => {
  const textContext = context({ marker: globalMarker, text: `用户 A 的测试标记是 ${globalMarker}。` });
  const messages = [{
    role: 'user',
    content: [
      { type: 'text', text: textContext },
      { type: 'image_url', image_url: { url: `data:image/png;base64,${projectMarker}` } },
    ],
  }];
  assert.deepEqual(findFixtureKnowledgeEvidence(messages, 'GLOBAL'), {
    marker: globalMarker, citationId: 3,
  });
  assert.equal(findFixtureKnowledgeEvidence(messages, 'PROJECT'), null);
});

test('retrieved and citation sections may span multiple text parts without trusting non-text parts', () => {
  const full = context({ marker: globalMarker, text: `用户 A 的测试标记是 ${globalMarker}。` });
  const splitAt = full.indexOf('[Citation Policy]');
  const messages = [{
    role: 'user',
    content: [
      { type: 'text', text: full.slice(0, splitAt) },
      { type: 'text', text: full.slice(splitAt) },
      { type: 'image_url', image_url: { url: `https://invalid.test/${projectMarker}` } },
    ],
  }];
  assert.deepEqual(groundedFixtureKnowledgeReply(messages), {
    content: `根据当前可用资料，测试标记是 ${globalMarker} [3]。`,
  });
});

test('newest RAG context wins and stale older evidence cannot override it', () => {
  const old = context({ marker: globalMarker, text: `用户 A 的测试标记是 ${globalMarker}。`, citationId: 3 });
  const newestMarker = 'AGENTMESH_V41_GLOBAL_9999999999999';
  const newest = context({ marker: newestMarker, text: `用户 A 的测试标记是 ${newestMarker}。`, citationId: 7, available: '[7]' })
    .replace('[Evidence 1]\n[1] source=other.txt; score=0.98\ncitation=[1]\ndocument_id=chunk-other\nsource=other.txt\n\n其他资料：无关。\n\n', '');
  assert.deepEqual(findFixtureKnowledgeEvidence([
    { role: 'user', content: old },
    { role: 'assistant', content: 'intermediate' },
    { role: 'user', content: newest },
  ], 'GLOBAL'), { marker: newestMarker, citationId: 7 });
});

test('structured content without an actual text evidence block fails closed', () => {
  assert.equal(findFixtureKnowledgeEvidence([{
    role: 'user',
    content: [
      { type: 'image_url', image_url: { url: `https://invalid.test/${globalMarker}/[3]` } },
      { type: 'text', text: '[Current Task]\n请回答。' },
    ],
  }], 'GLOBAL'), null);
});
