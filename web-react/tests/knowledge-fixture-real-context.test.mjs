import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import {
  fixtureMessageText,
  findFixtureKnowledgeEvidence,
  groundedFixtureKnowledgeReply,
  probeFixtureKnowledgeEvidence,
} from '../e2e/knowledge-fixture-evidence.mjs';

const generator = fileURLToPath(new URL('./fixtures/generate-real-rag-context.py', import.meta.url));
const python = process.env.V4_1_E2E_RUNTIME_PYTHON || process.env.AGENTMESH_TEST_PYTHON ||
  (process.platform === 'win32' ? 'python' : 'python3');

function productionContext(kind) {
  // Windows Python otherwise writes its locale encoding while Node decodes UTF-8.
  // Force the child's output encoding instead of relying on shell environment.
  const result = spawnSync(python, [generator, kind], {
    encoding: 'utf8', timeout: 15000,
    env: { ...process.env, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8' },
  });
  assert.equal(result.status, 0, `production Context Builder fixture failed (${result.error?.code ?? result.stderr})`);
  return JSON.parse(result.stdout);
}

for (const kind of ['GLOBAL', 'PROJECT']) {
  test(`${kind}: actual Python Context Builder citation survives both transport shapes`, () => {
    const { context, marker, citationId } = productionContext(kind);
    const plain = [{ role: 'user', content: context }];
    const multimodal = [{ role: 'user', content: [
      { type: 'text', text: context },
      { type: 'image_url', image_url: { url: `data:image/png;base64,${marker}` } },
    ] }];
    for (const messages of [plain, multimodal]) {
      assert.deepEqual(findFixtureKnowledgeEvidence(messages, kind), { marker, citationId });
      assert.match(groundedFixtureKnowledgeReply(messages)?.content ?? '', new RegExp(`\\b${marker} \\[${citationId}\\]`));
      const probe = probeFixtureKnowledgeEvidence(messages, kind);
      assert.equal(probe.diagnostic.reason, 'valid_evidence');
      assert.equal(probe.diagnostic.allowedCount, 2);
      assert.equal(probe.diagnostic.validIdentityCount, 2);
      assert.equal(probe.diagnostic.markerEvidenceCount, 1);
      assert.equal(JSON.stringify(probe.diagnostic).includes(marker), false, 'diagnostics must not leak marker');
      assert.equal(JSON.stringify(probe.diagnostic).includes('knowledge.txt'), false, 'diagnostics must not leak sources');
    }
  });

  test(`${kind}: text parts may split evidence header, identity, marker and citation policy mid-token`, () => {
    const { context, marker, citationId } = productionContext(kind);
    const points = [context.indexOf('[Evidence 2]') + 4, context.indexOf('document_id=qa-production-chunk-2') + 5,
      context.indexOf(marker) + 10, context.indexOf('available_citations=') + 12];
    assert.ok(points.every((item) => item > 4));
    const slices = [];
    let start = 0;
    for (const end of points.sort((a, b) => a - b)) {
      slices.push({ type: 'text', text: context.slice(start, end) });
      start = end;
    }
    slices.push({ type: 'text', text: context.slice(start) });
    assert.equal(fixtureMessageText(slices), context);
    assert.deepEqual(findFixtureKnowledgeEvidence([{ role: 'user', content: slices }], kind), { marker, citationId });
  });

  test(`${kind}: newer malformed retrieval cannot be rescued by stale prior request`, () => {
    const { context, marker } = productionContext(kind);
    const newer = context.replace('citation=[2]', 'citation=[9]');
    const messages = [
      { role: 'user', content: context },
      { role: 'assistant', content: 'previous completion' },
      { role: 'user', content: newer },
    ];
    assert.equal(findFixtureKnowledgeEvidence(messages, kind), null);
    const diagnostic = probeFixtureKnowledgeEvidence(messages, kind).diagnostic;
    assert.equal(diagnostic.reason, 'marker_not_in_valid_evidence_body');
    assert.equal(JSON.stringify(diagnostic).includes(marker), false);
  });

  test(`${kind}: unrelated old citation blocks in memory cannot shadow actual retrieved section`, () => {
    const { context, marker, citationId } = productionContext(kind);
    const withHistoricalBlock = `[Conversation Memory]\nuser: earlier transcript:\n[Retrieved Knowledge]\nold\n[Citation Policy]\navailable_citations=[7]\n\n${context}`;
    assert.deepEqual(findFixtureKnowledgeEvidence([{ role: 'user', content: withHistoricalBlock }], kind), { marker, citationId });
  });

  test(`${kind}: marker outside valid evidence and forged non-text parts remain disallowed`, () => {
    const { context, marker } = productionContext(kind);
    const withoutEvidenceMarker = context.replace(`测试标记是 ${marker}。`, '测试标记未提供。');
    const inputs = [
      [{ role: 'user', content: `[Conversation Memory]\n${marker}\n\n${withoutEvidenceMarker}` }],
      [{ role: 'user', content: [
        { type: 'text', text: withoutEvidenceMarker },
        { type: 'image_url', image_url: { url: `https://invalid.test/${marker}` } },
      ] }],
      [{ role: 'user', content: withoutEvidenceMarker.replace('available_citations=[1] [2]', 'available_citations=[1]') }],
    ];
    for (const messages of inputs) assert.equal(findFixtureKnowledgeEvidence(messages, kind), null);
  });
}

test('numeric-only diagnostics distinguish flattened marker presence from validated evidence', () => {
  const { context, marker } = productionContext('GLOBAL');
  const withoutMarker = context.replace(`测试标记是 ${marker}。`, '其他内容。');
  const probe = probeFixtureKnowledgeEvidence([{ role: 'user', content: `[Conversation Memory]\n${marker}\n\n${withoutMarker}` }], 'GLOBAL');
  assert.equal(probe.evidence, null);
  assert.equal(probe.diagnostic.markerInText, true);
  assert.equal(probe.diagnostic.markerInRetrieved, false);
  assert.equal(probe.diagnostic.reason, 'marker_outside_retrieved_evidence');
  assert.doesNotMatch(JSON.stringify(probe.diagnostic), /AGENTMESH|knowledge\.txt|chunk-/);
});

test('later ordinary user turn never reuses prior consented Global evidence', () => {
  const { context, marker } = productionContext('GLOBAL');
  const messages = [
    { role: 'user', content: context },
    { role: 'assistant', content: `Earlier authorized response ${marker} [2]` },
    { role: 'user', content: '现在没有启用任何全局知识，请改写这句话。' },
  ];
  assert.equal(findFixtureKnowledgeEvidence(messages, 'GLOBAL'), null);
  assert.equal(probeFixtureKnowledgeEvidence(messages, 'GLOBAL').diagnostic.reason, 'no_retrieved_section');
});

test('empty latest user content cannot fall back to a previous authorized RAG turn', () => {
  const { context } = productionContext('GLOBAL');
  const input = [
    { role: 'user', content: context },
    { role: 'user', content: [{ type: 'image_url', image_url: { url: 'data:image/png;base64,AA==' } }] },
  ];
  assert.equal(findFixtureKnowledgeEvidence(input, 'GLOBAL'), null);
  assert.equal(probeFixtureKnowledgeEvidence(input, 'GLOBAL').diagnostic.reason, 'empty_latest_user_message');
});
