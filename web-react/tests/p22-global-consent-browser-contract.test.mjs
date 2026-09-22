import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const read = (file) => readFileSync(new URL(`../${file}`, import.meta.url), 'utf8');
const workspace = read('src/features/workspace/Workspace.tsx');
const config = read('src/features/workspace/RunConfiguration.tsx');
const drawer = read('src/features/workspace/RunSettingsDrawer.tsx');
const harness = read('e2e/v4-1-browser-e2e.mjs');
const goPolicy = read('../backend-go/internal/service/rag_policy.go');

function between(start, end) {
  const from = harness.indexOf(start);
  const to = harness.indexOf(end, from + start.length);
  assert.ok(from >= 0 && to > from, `missing acceptance section ${start}`);
  return harness.slice(from, to);
}

test('Global KB upload alone cannot authorize knowledge and existing Workspace defaults remain strict', () => {
  assert.match(workspace, /useState<RagScope\[\]>\(\["PROJECT"\]\)/);
  assert.match(workspace, /data-testid="run-settings-open"/);
  assert.match(config, /data-testid="rag-scope-user-global"/);
  assert.match(config, /我的全局知识（显式开启）/);
  assert.match(drawer, /data-testid="run-settings-done"/);
  assert.match(goPolicy, /!allowedScope\[model\.RagScopeUserGlobal\] \|\| base\.UserID != uid/);
});

test('Chrome opts in and out through real UI, not by fabricated API scopes', () => {
  const helper = between('async function setUserGlobalKnowledgeScope(cdp, enabled)', '// Store only the policy fields');
  assert.match(helper, /await waitFor\(/);
  assert.match(helper, /run-settings-open/);
  assert.match(helper, /rag-scope-user-global/);
  assert.match(helper, /await clickSelector\(cdp, scopeSelector/);
  assert.match(helper, /run-settings-done/);
  assert.match(helper, /global knowledge consent state/);
  assert.doesNotMatch(helper, /apiRequest\(|fetch\(|ragPolicy\s*:\s*\{/);
});

test('Chrome covers negative upload-only case, AUTO positive discovery and isolation without short-circuiting', () => {
  const flow = between('    // 3) Natural GLOBAL Knowledge and isolation.', '    console.log("AgentMesh V4.1 Real-stack Browser E2E: PASS")');
  const negative = flow.indexOf('assertObservedGlobalKnowledgeSubmission(globalKnowledgeSubmissions, false');
  const positive = flow.indexOf('assertObservedGlobalKnowledgeSubmission(globalKnowledgeSubmissions, true, "A');
  const project = flow.indexOf('unbound GLOBAL Knowledge leaked into PROJECT conversation');
  const crossUser = flow.indexOf('assertObservedGlobalKnowledgeSubmission(globalKnowledgeSubmissions, true, "B');
  assert.ok(negative >= 0 && positive > negative && project > positive && crossUser > project);
  assert.match(flow, /await setUserGlobalKnowledgeScope\(cdp, true\);[\s\S]*?await sendPrompt\(cdp, globalKnowledgePrompt, globalMarker, 120000\)/);
  assert.match(flow, /lastModelContextHadGlobalMarker/);
  assert.match(flow, /retrievalHits > 0/);
  assert.match(flow, /await setUserGlobalKnowledgeScope\(cdp, false\);\s*project = await apiRequest/);
  assert.match(flow, /data-knowledge-selected="true"/);
  assert.match(flow, /GLOBAL Knowledge leaked without explicit user consent/);
  assert.match(flow, /User B retrieved User A GLOBAL Knowledge marker/);
  assert.doesNotMatch(flow, /expectedText\s*=\s*''|test\.skip\(|TODO_GLOBAL|forceGlobalAccess/);
});

test('Browser captures only consent metadata and never forces KB selection', () => {
  const summary = between('function summarizeGlobalKnowledgeSubmission(', 'function assertObservedGlobalKnowledgeSubmission(');
  const assertion = between('function assertObservedGlobalKnowledgeSubmission(', 'async function verifyAndReloadV41ModelService(');
  assert.match(summary, /request\.postData/);
  assert.match(summary, /payload\.ragPolicy\?\.scopes/);
  assert.doesNotMatch(summary, /JSON\.stringify\(payload\)|Authorization|console\.log\(payload\)/);
  assert.match(assertion, /assert\.equal\(policy\.mode, 'AUTO'/);
  assert.match(assertion, /assert\.deepEqual\(policy\.selectedKnowledgeBaseIds, \[\]/);
});
