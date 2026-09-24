import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');
const api = read('src/api.ts');
const workspace = read('src/features/workspace/Workspace.tsx');
const config = read('src/features/workspace/RunConfiguration.tsx');
const router = read('../backend-go/internal/router/task.go');
const handler = read('../backend-go/internal/handler/handlers.go');
const policy = read('../backend-go/internal/service/rag_policy.go');
const engine = read('../runtime-python/app/services/engine.py');

test('Knowledge Runtime single POST route decides on the accepted request (no double-submit preflight)', () => {
  assert.match(router, /"\/tasks\/submit-stream"/);
  assert.match(handler, /func \(h \*TaskHandler\) RunAutoStream\(/);
  assert.match(handler, /decision := h\.s\.DecideDeliveryMode\(input\)/);
  assert.match(api, /input\.deliveryMode === "auto"\s*\? "\/api\/tasks\/submit-stream"/);
  assert.doesNotMatch(workspace, /await decideTaskExecutionRoute\(/);
});

test('Knowledge Runtime default is AUTO and durable result is observed by existing pending-poll fallback', () => {
  assert.match(workspace, /useState<DeliveryMode>\(\s*"auto"/);
  assert.match(workspace, /latestRun\.task\.deliveryMode === "durable"/);
  assert.match(workspace, /reloadMessages\((?:current\.id|conversationId)\)/);
  assert.match(workspace, /subscribeDurableTaskEvents\(/);
  assert.match(workspace, /if \(!streaming\) refresh\(\)/);
});

test('RAG V1.1 global knowledge requires explicit user opt-in and Go hard OFF filters metadata', () => {
  assert.match(config, /ragScopes\.includes\("USER_GLOBAL"\)/);
  assert.match(config, /我的全局知识（显式开启）/);
  assert.match(policy, /if !allowedScope\[model\.RagScopeUserGlobal\]/);
  assert.match(policy, /if normalized\.Mode == model\.RagModeOff/);
});

test('RAG V1.1 optional KB selection remains bounded to displayed scope and checked at Go', () => {
  assert.match(config, /指定知识库（可选）/);
  assert.match(workspace, /selectedKnowledgeBaseIds\.filter\(\(id\) =>/);
  assert.match(policy, /if !allowedSet\[id\]/);
});

test('RAG V1.1 effective policy gates retrieval without Engine overriding discovery score', () => {
  assert.match(engine, /policy_mode == "OFF" or explicit_rag_off/);
  assert.match(engine, /knowledge_discovery\.selected_knowledge_base_ids/);
  assert.doesNotMatch(engine, /if capability_plan\.use_project_knowledge:\s*# force FAST/);
});
