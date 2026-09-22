import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const browser = readFileSync(new URL('../e2e/v4-1-browser-e2e.mjs', import.meta.url), 'utf8');

test('Global and Project acceptance require actual fixture evidence decisions, not a flattened marker', () => {
  assert.match(browser, /knowledgeProbes\.push\(\{/);
  assert.match(browser, /knowledgeProbes\.length > 32/);
  assert.match(browser, /item\.requestIndex > modelRequestsBeforeGlobal/);
  assert.match(browser, /item\.global\.reason === "valid_evidence" && item\.replyKind === "global_grounded"/);
  assert.match(browser, /item\.requestIndex > modelRequestsBeforeProject/);
  assert.match(browser, /item\.project\.reason === "valid_evidence" && item\.replyKind === "project_grounded"/);
  assert.match(browser, /await sendPrompt\(cdp, globalKnowledgePrompt, globalMarker, 120000\)/);
  assert.match(browser, /await sendPrompt\(cdp, "请根据当前项目资料告诉我项目测试标记是什么？", projectMarker, 120000\)/);
});

test('Failure diagnostics retain original error and expose only structural probe data', () => {
  assert.match(browser, /reportFailurePreservingPrimary\(error, "\[P22 GLOBAL\]"/);
  assert.match(browser, /reportFailurePreservingPrimary\(error, "\[P22 PROJECT\]"/);
  const probeBlock = browser.slice(browser.indexOf('knowledgeProbes.push({'), browser.indexOf('if (knowledgeProbes.length > 32)'));
  assert.match(probeBlock, /requestIndex: requestCount/);
  assert.match(probeBlock, /global: globalProbe.diagnostic/);
  assert.match(probeBlock, /project: projectProbe.diagnostic/);
  assert.doesNotMatch(probeBlock, /JSON\.stringify\(messages\)|content:|lastUser:|lastMessageText:|documentId:|source:/);
});

test('Previously blocked isolation and Citation Guard browser assertions still run', () => {
  assert.match(browser, /PROJECT citation guard must pass/);
  assert.match(browser, /PROJECT Knowledge had no projected used citations/);
  assert.match(browser, /unbound GLOBAL Knowledge leaked into PROJECT conversation/);
  assert.match(browser, /User B retrieved User A GLOBAL Knowledge marker/);
  assert.match(browser, /AgentMesh V4\.1 Real-stack Browser E2E: PASS/);
});
