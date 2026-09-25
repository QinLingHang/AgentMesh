import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const webRoot = path.resolve(import.meta.dirname, "..");
const source = (...parts) => fs.readFileSync(path.join(webRoot, ...parts), "utf8");

test("V4.1 Browser Reliability exposes stable conversation and Run Details browser hooks", () => {
  const sessionRail = source("src", "features", "workspace", "SessionRail.tsx");
  const workspace = source("src", "features", "workspace", "Workspace.tsx");
  const history = source("src", "features", "workspace", "MessageHistory.tsx");
  const latest = source("src", "features", "workspace", "LatestRunMeta.tsx");
  const tabs = source("src", "features", "run-details", "RunDetailsTabs.tsx");
  const capability = source("src", "features", "run-details", "CapabilityDiscoveryPanel.tsx");
  const desktop = source("src", "features", "run-details", "DesktopTracePanel.tsx");

  for (const marker of ["conversation-create", "conversation-item-"]) assert.match(sessionRail, new RegExp(marker));
  for (const marker of ["workspace-conversation", "workspace-composer", "workspace-submit", "run-details-drawer"]) assert.match(workspace, new RegExp(marker));
  for (const marker of ["message-user", "message-assistant"]) assert.match(history, new RegExp(marker));
  assert.match(latest, /run-details-open/);
  assert.match(tabs, /run-details-tab-/);
  assert.match(capability, /capability-discovery-event/);
  assert.match(capability, /data-knowledge-selected/);
  assert.match(desktop, /desktop-trace-event/);
  assert.match(desktop, /data-tool=\{tool\}/);
});

test("V4.1 Browser Reliability real-stack harness covers all mandatory dynamic cases", () => {
  const harness = source("e2e", "v4-1-browser-e2e.mjs");

  assert.match(harness, /late B response overwrote active conversation A/);
  assert.match(harness, /local\.fs\.list/);
  assert.match(harness, /real Desktop Bridge preflight failed/);
  assert.match(harness, /GLOBAL Knowledge/);
  assert.match(harness, /data-knowledge-selected/);
  assert.match(harness, /unbound GLOBAL Knowledge leaked into PROJECT conversation/);
  assert.match(harness, /User B retrieved User A GLOBAL Knowledge marker/);
  assert.match(harness, /PRIVATE_SECRET_SHOULD_NOT_TRACE/);
  assert.match(harness, /runtime returned 500 Internal Server Error/);
});

test("V4.1 Dispatcher Lease Reliability acceptance harness uses the real Desktop ASGI module and single-fixture Go stress", () => {
  const harness = source("e2e", "v4-1-browser-e2e.mjs");
  const script = fs.readFileSync(path.join(webRoot, "..", "scripts", "TEST_BROWSER_E2E.ps1"), "utf8");
  const goLeaseTest = fs.readFileSync(path.join(webRoot, "..", "backend-go", "internal", "service", "v3_distributed_runtime_integration_test.go"), "utf8");

  assert.match(harness, /desktop_bridge\.app:app/);
  assert.doesNotMatch(harness, /desktop_bridge\.main:app/);

  assert.match(script, /V4_1_LEASE_STRESS_ITERATIONS/);
  assert.match(script, /TestV3DispatcherLeaseFailoverStress/);
  assert.doesNotMatch(script, /-count=\$GoStressCount/);

  assert.match(goLeaseTest, /func TestV3DispatcherLeaseFailoverStress/);
  assert.match(goLeaseTest, /V4_1_LEASE_STRESS_ITERATIONS/);
  assert.match(goLeaseTest, /DATE_SUB\(UTC_TIMESTAMP\(6\), INTERVAL 1 SECOND\)/);
});


test("V4.1 Desktop Authorization authorizes the real Desktop fixture through the Bridge's canonical JSON allowlist", () => {
  const harness = source("e2e", "v4-1-browser-e2e.mjs");

  assert.match(harness, /DESKTOP_ALLOWED_ROOTS_JSON:\s*JSON\.stringify\(\[desktopFixtureRoot\]\)/);
  assert.doesNotMatch(harness, /DESKTOP_ALLOWED_ROOTS:\s*desktopFixtureRoot/);
  assert.doesNotMatch(harness, /DESKTOP_BRIDGE_ALLOWED_ROOTS:\s*desktopFixtureRoot/);
  assert.doesNotMatch(harness, /AGENTMESH_DESKTOP_ALLOWED_ROOTS:\s*desktopFixtureRoot/);
});


test("V4.1 Model Fixture seeds an encrypted enabled local model service for both real browser users without weakening production URL validation", () => {
  const harness = source("e2e", "v4-1-browser-e2e.mjs");
  const fixture = fs.readFileSync(path.join(webRoot, "..", "backend-go", "cmd", "browser-e2e-fixture", "main.go"), "utf8");
  const governance = fs.readFileSync(path.join(webRoot, "..", "backend-go", "internal", "service", "governance.go"), "utf8");

  assert.match(harness, /seed-v4-1-model-service/);
  assert.match(harness, /verifyAndReloadV41ModelService\(cdp, fixture, apiBase, tokenA, ownerA\.email/);
  assert.match(harness, /verifyAndReloadV41ModelService\(cdp, fixture, apiBase, tokenB, ownerB\.email/);
  assert.match(harness, /GET", "\/api\/me\/model-services"/);
  assert.match(harness, /Page\.reload/);

  assert.match(fixture, /case "seed-v4-1-model-service"/);
  assert.match(fixture, /V4_1_FIXTURE_GOVERNANCE_MASTER_KEY/);
  assert.match(fixture, /V4_1_FIXTURE_MODEL_API_KEY/);
  assert.match(fixture, /agentmesh:user:%d:model-service:%s/);
  assert.match(fixture, /cipher\.NewGCM/);
  assert.match(fixture, /enabled,auto_route,is_default/);
  assert.match(fixture, /"openai-compatible"/);
  assert.match(fixture, /http:\/\/127\.0\.0\.1:/);

  assert.match(governance, /u\.Scheme != "https"/);
  assert.match(governance, /ip\.IsLoopback\(\) \|\| ip\.IsPrivate\(\)/);
});

test("V4.1 Delayed Provider waits for the real submit gate and arms a marker-correlated delayed provider request", () => {
  const harness = source("e2e", "v4-1-browser-e2e.mjs");

  assert.match(harness, /delayed B submit enabled/);
  assert.match(harness, /workspace-submit.*disabled === false/s);
  assert.match(harness, /\/control\/hold/);
  assert.match(harness, /holdMarker/);
  assert.match(harness, /requestCount/);
  assert.match(harness, /lastMessageText/);
  assert.match(harness, /delayed B user prompt/);
  assert.match(harness, /delayed model request never reached armed fixture/);
});


test("V4.1 Conversation Selection selects a successfully created conversation before best-effort projection refresh", () => {
  const workspace = source("src", "features", "workspace", "Workspace.tsx");
  const start = workspace.indexOf("const create = async");
  const end = workspace.indexOf("const openConversation", start);

  assert.ok(start >= 0 && end > start, "Workspace.create block must be present");
  const createBlock = workspace.slice(start, end);

  assert.doesNotMatch(createBlock, /await Promise\.all\(\[/);
  assert.ok((createBlock.match(/Promise\.allSettled/g) ?? []).length >= 2);

  const selectCreated = createBlock.lastIndexOf("setCurrent(");
  const successRefresh = createBlock.lastIndexOf("void Promise.allSettled");
  assert.ok(selectCreated >= 0, "successful create path must select the created conversation");
  assert.ok(successRefresh > selectCreated, "projection refresh must happen only after current conversation selection");
  assert.match(createBlock, /authoritative mutation/);
  assert.match(createBlock, /best-effort follow-up work/);
  assert.match(createBlock, /transient project-list failure/);
});


test("V4.1 Conversation Ownership prevents stale conversation projections from overriding an explicit current selection", () => {
  const app = source("src", "App.tsx");
  const start = app.indexOf("const loadConversations =");
  const end = app.indexOf("const loadProjects =", start);

  assert.ok(start >= 0 && end > start, "App.loadConversations block must be present");
  const loadBlock = app.slice(start, end);

  assert.match(app, /const conversationLoadSequenceRef = useRef\(0\)/);
  assert.match(loadBlock, /\+\+conversationLoadSequenceRef\.current/);
  assert.match(loadBlock, /sequence !==\s*conversationLoadSequenceRef\.current/s);
  assert.match(loadBlock, /return;\s*}\s*\n\s*setConversations/s);
  assert.match(loadBlock, /refreshed \?\?\s*previous/s);
  assert.doesNotMatch(loadBlock, /if \(refreshed\)[\s\S]*result\[0\]/);
  assert.match(loadBlock, /Explicit user selection \/ successful mutation is authoritative/);
  assert.match(loadBlock, /older list snapshot must not write A back over an authoritative B/);
});


test("V4.1 Auto-title Ownership prevents a late auto-title result from stealing current conversation", () => {
  const workspace = source("src", "features", "workspace", "Workspace.tsx");
  const start = workspace.indexOf("if (UNTITLED_TITLES.has(conversation.title))");
  const end = workspace.indexOf("await Promise.all([", start);

  assert.ok(start >= 0 && end > start, "Workspace auto-title block must be present");
  const autoTitleBlock = workspace.slice(start, end);

  assert.match(autoTitleBlock, /const renamed = await renameConversation/);
  assert.match(autoTitleBlock, /conversation = renamed/);
  assert.doesNotMatch(autoTitleBlock, /setCurrent\(renamed\)/);
  assert.match(autoTitleBlock, /renameConversation is already responsible for updating the active/);
  assert.match(autoTitleBlock, /user may have created\/selected another conversation while the/);

  const app = source("src", "App.tsx");
  const renameStart = app.indexOf("const handleRenameConversation =");
  const renameEnd = app.indexOf("const handleDeleteConversation =", renameStart);
  assert.ok(renameStart >= 0 && renameEnd > renameStart, "App.handleRenameConversation block must be present");
  const renameBlock = app.slice(renameStart, renameEnd);

  assert.match(renameBlock, /setCurrent\(\s*\(item\) =>/s);
  assert.match(renameBlock, /item\?\.id ===\s*updated\.id/s);
  assert.match(renameBlock, /\? updated\s*:\s*item/s);
});

test("V4.1 Stream Ownership keeps late direct-stream UI writes owned by the submitting conversation", () => {
  const workspace = source("src", "features", "workspace", "Workspace.tsx");
  const runStart = workspace.indexOf("const run = async");
  const runEnd = workspace.indexOf("const resume = async", runStart);

  assert.ok(runStart >= 0 && runEnd > runStart, "Workspace.run block must be present");
  const runBlock = workspace.slice(runStart, runEnd);

  assert.match(workspace, /const activeConversationIdRef = useRef<number \| null>\(current\?\.id \?\? null\)/);
  assert.match(workspace, /activeConversationIdRef\.current = current\?\.id \?\? null/);
  assert.match(runBlock, /const submissionConversationId = conversation\.id/);
  assert.match(runBlock, /const isSubmissionConversationActive = \(\) =>\s*activeConversationIdRef\.current === submissionConversationId/s);

  const deltaStart = runBlock.indexOf("onDelta:");
  const statusStart = runBlock.indexOf("onStatus:", deltaStart);
  assert.ok(deltaStart >= 0 && statusStart > deltaStart, "direct stream callbacks must be present");
  const deltaBlock = runBlock.slice(deltaStart, statusStart);
  assert.match(deltaBlock, /if \(!isSubmissionConversationActive\(\)\) return/);
  assert.match(deltaBlock, /setStreamingAnswer/);

  const statusBlock = runBlock.slice(statusStart, runBlock.indexOf("})", statusStart) + 2);
  assert.match(statusBlock, /if \(!isSubmissionConversationActive\(\)\) return/);
  assert.match(statusBlock, /setStreamingPhase/);

  assert.match(runBlock, /if \(isSubmissionConversationActive\(\)\) \{\s*completionRefreshes\.unshift\(reloadMessages\(submissionConversationId\)\)/s);
  assert.doesNotMatch(runBlock, /await Promise\.all\(\[\s*reloadMessages\(conversation\.id\),\s*reloadTasks\(\),\s*reloadConversations\(\)/s);
  assert.match(runBlock, /Never restore a background\s*\/\/ conversation's prompt\/attachments into another active conversation/s);
});


test("V4.1 History Anchor keeps stream ownership build-safe and provisions the real Full Runtime Agent prerequisite", () => {
  const workspace = source("src", "features", "workspace", "Workspace.tsx");
  const harness = source("e2e", "v4-1-browser-e2e.mjs");

  assert.match(workspace, /const submissionConversationId = conversation\.id/);
  assert.match(workspace, /activeConversationIdRef\.current === submissionConversationId/);
  assert.match(workspace, /conversationId: submissionConversationId/);
  assert.match(workspace, /reloadMessages\(submissionConversationId\)/);

  assert.match(harness, /async function ensureV41AgentBaseline/);
  assert.match(harness, /POST", "\/api\/agents\/seed-demo"/);
  assert.match(harness, /GET", "\/api\/agents"/);
  assert.match(harness, /GeneralAgent/);
  assert.match(harness, /await ensureV41AgentBaseline\(apiBase, accessToken, email\)/);
  assert.match(harness, /do not weaken TaskService\.loadRuntimeResources/);

  assert.match(harness, /A authoritative user history after reload/);
  assert.match(harness, /A authoritative assistant history after reload/);
  assert.match(harness, /B delayed user message leaked into A after reload/);
  assert.match(harness, /B delayed assistant response leaked into A after reload/);
});

test("V4.1 History Loading models conversation history loading explicitly and waits for authoritative rows", () => {
  const app = source("src", "App.tsx");
  const workspace = source("src", "features", "workspace", "Workspace.tsx");
  const history = source("src", "features", "workspace", "MessageHistory.tsx");
  const harness = source("e2e", "v4-1-browser-e2e.mjs");

  assert.match(app, /messageProjection/);
  assert.match(app, /conversationId:\s*number \| null/);
  assert.match(app, /const currentConversationIdRef = useRef<number \| null>\(current\?\.id \?\? null\)/);
  assert.match(app, /currentConversationIdRef\.current = current\?\.id \?\? null/);
  assert.match(app, /sequence !== messageLoadSequenceRef\.current/);
  assert.match(app, /currentConversationIdRef\.current !== id/);
  assert.match(app, /messageProjection\.conversationId === current\.id/);
  assert.match(app, /const messagesLoading =/);
  assert.match(app, /messageProjection\.conversationId !== current\.id/);
  assert.match(app, /会话记录加载失败，请稍后重试/);

  assert.match(workspace, /data-messages-state=\{messagesLoading \? "loading" : messagesLoadError \? "error" : "ready"\}/);
  assert.match(workspace, /aria-busy=\{messagesLoading\}/);
  assert.match(history, /data-testid="message-history-loading"/);
  assert.match(history, /正在加载会话记录/);
  assert.match(history, /data-testid="message-history-error"/);

  assert.match(harness, /async function waitForConversationHistoryReady/);
  assert.match(harness, /dataset\?\.messagesState !== "loading"/);
  assert.match(harness, /historyState\.state,\s*"ready"/s);
  assert.match(harness, /A authoritative user history after reload/);
  assert.match(harness, /A authoritative assistant history after reload/);
  assert.doesNotMatch(harness, /assert\.ok\(reloadedAText\.includes\(aMarker\)/);
  assert.doesNotMatch(harness, /assert\.ok\(reloadedAText\.includes\(`CONVERSATION_REPLY_\$\{aMarker\}`\)/);
});


test("V4.1 Run Details Loading removes stale history contracts and waits for lazy Run Details tabs", () => {
  const harness = source("e2e", "v4-1-browser-e2e.mjs");

  assert.doesNotMatch(harness, /A history missing after reload and switch-back/);
  assert.match(harness, /A authoritative user history after reload/);
  assert.match(harness, /A authoritative assistant history after reload/);

  const detailsStart = harness.indexOf("async function openLatestRunDetails");
  const detailsEnd = harness.indexOf("async function closeRunDetails", detailsStart);
  assert.ok(detailsStart >= 0 && detailsEnd > detailsStart, "Run Details open helper must be present");
  const detailsBlock = harness.slice(detailsStart, detailsEnd);
  assert.match(detailsBlock, /run-details-drawer/);
  assert.match(detailsBlock, /data-testid\^=\"run-details-tab-/);
  assert.match(detailsBlock, /Run Details lazy tab surface/);
  assert.doesNotMatch(detailsBlock, /await sleep\(/);
});

test("Desktop-only outage acceptance proves the owned Windows listener is down", () => {
  const harness = source("e2e", "v4-1-browser-e2e.mjs");

  assert.match(harness, /V4_1_E2E_DESKTOP_ONLY/);
  assert.match(harness, /async function stopOwnedLoopbackListener/);
  assert.match(harness, /Get-NetTCPConnection/);
  assert.match(harness, /async function captureDesktopBridgeOwnership/);
  assert.match(harness, /desktop\.__agentmeshQaDesktopOwnership = await captureDesktopBridgeOwnership/);
  assert.match(harness, /listenerIdentityMatches/);
  assert.match(harness, /Refusing to kill an unowned process/);
  assert.doesNotMatch(harness, /Stop-Process -Id \$_\.OwningProcess -Force/);
  assert.match(harness, /Desktop Bridge still listening on its owned QA port/);
  assert.match(harness, /safeMessageVisible/);
  assert.match(harness, /requestDiagnostics/);
});
