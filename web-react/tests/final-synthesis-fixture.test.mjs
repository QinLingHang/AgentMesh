import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { join, dirname } from 'node:path';
import test from 'node:test';
import { groundedFixtureKnowledgeReply, probeFixtureKnowledgeEvidence } from '../e2e/knowledge-fixture-evidence.mjs';

const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const generator = join(root, 'runtime-python', 'tests', 'fixtures', 'generate-synthesis-context.py');
const python = process.env.V4_1_E2E_RUNTIME_PYTHON || process.env.AGENTMESH_TEST_PYTHON || 'python';
function data(kind) {
  return JSON.parse(execFileSync(python, [generator, kind], { encoding: 'utf8', timeout: 20000 }));
}
for (const kind of ['GLOBAL', 'PROJECT']) {
  test(`final ${kind} synthesis consumes real evidence and exact citation`, () => {
    const fixture = data(kind);
    const messages = [{ role: 'user', content: fixture.prompt }];
    const found = probeFixtureKnowledgeEvidence(messages, kind);
    assert.equal(found.diagnostic.reason, 'valid_evidence');
    assert.equal(found.evidence?.citationId, 2);
    assert.equal(found.evidence?.marker, fixture.marker);
    const reply = groundedFixtureKnowledgeReply(messages);
    assert.ok(reply?.content.includes(`${fixture.marker} [2]`));
    assert.equal(fixture.validCitation, true);
    assert.equal(fixture.wrongCitationRejected, true);
    assert.equal(fixture.missingCitationRejected, true);
  });
  test(`final ${kind} synthesis with no approved hits cannot reuse fake prior evidence`, () => {
    const fixture = data(kind);
    const messages = [{ role: 'user', content: fixture.zeroPrompt }];
    assert.equal(groundedFixtureKnowledgeReply(messages), null);
    const diagnostic = probeFixtureKnowledgeEvidence(messages, kind).diagnostic;
    assert.equal(diagnostic.reason, 'no_retrieved_section');
    assert.equal(diagnostic.markerInText, true);
    assert.equal(diagnostic.markerInRetrieved, false);
  });
}
