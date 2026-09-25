import fs from "node:fs";
import test from "node:test";
import assert from "node:assert/strict";

const app = fs.readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
const api = fs.readFileSync(new URL("../src/api.ts", import.meta.url), "utf8");
const history = fs.readFileSync(new URL("../src/features/workspace/MessageHistory.tsx", import.meta.url), "utf8");
const workspace = fs.readFileSync(new URL("../src/features/workspace/Workspace.tsx", import.meta.url), "utf8");
const workspaceCss = fs.readFileSync(new URL("../src/styles/workspace.css", import.meta.url), "utf8");
const v41Browser = fs.readFileSync(new URL("../e2e/v4-1-browser-e2e.mjs", import.meta.url), "utf8");

test("Conversation Reliability history uses cursor pagination rather than a fixed visible tail", () => {
  assert.match(api, /listMessagePage/);
  assert.match(api, /beforeId/);
  assert.match(app, /loadOlderMessages/);
  assert.match(history, /加载更早的会话记录/);
  assert.doesNotMatch(history, /messages\.slice\(-20\)/);
});

test("Conversation Reliability history keeps late assistant results owned by their request turn", () => {
  assert.match(history, /orderMessagesByTurn/);
  assert.match(history, /message\.requestId/);
  assert.match(history, /latestRun\.task\.requestId/);
});

test("Conversation Reliability semantic marker rename preserves the deterministic fixture contract", () => {
  assert.match(v41Browser, /const aMarker = `CONVERSATION_A_\$\{stamp\}`/);
  assert.match(v41Browser, /user\.match\(\/CONVERSATION_\[AB\]_\[A-Z0-9_/);
  assert.match(v41Browser, /return \{ content: `CONVERSATION_REPLY_\$\{marker\}` \}/);
  assert.match(v41Browser, /await sendPrompt\(cdp, aMarker, `CONVERSATION_REPLY_\$\{aMarker\}`\)/);
  assert.doesNotMatch(v41Browser, /Browser Reliability_\[AB\]/);
});


test("Conversation Reliability durable reply synchronization reuses the canonical API client and legal history paging", () => {
  const helperStart = v41Browser.indexOf("async function waitForRecentConversationMessagePersistence");
  assert.ok(helperStart >= 0, "durable reply synchronization helper must exist");
  const helperEnd = v41Browser.indexOf("async function createConversationThroughBrowser", helperStart);
  assert.ok(helperEnd > helperStart, "durable reply synchronization helper boundary must exist");
  const helper = v41Browser.slice(helperStart, helperEnd);

  assert.match(helper, /apiRequest\(/);
  assert.match(helper, /messages\/page\?limit=100/);
  assert.doesNotMatch(helper, /limit=200/);
  assert.doesNotMatch(helper, /cdp\.evaluate/);
  assert.match(v41Browser, /await waitForRecentConversationMessagePersistence\(\s*apiBase,\s*tokenA,\s*convB/s);
});

test("Conversation Reliability conversation opening lands at the true bottom without hijacking manual history reading", () => {
  assert.match(workspace, /data-testid="workspace-message-scroll"/);
  assert.match(workspace, /messagesLoading/);
  assert.match(workspace, /conversationChanged \|\| shouldAutoFollowMessagesRef\.current/);
  assert.match(workspace, /scrollNode\.scrollHeight\s*-\s*scrollNode\.clientHeight/);
  assert.match(workspace, /distanceFromBottom <= 96/);
  assert.match(workspace, /ResizeObserver/);
});

test("loading older history preserves the concrete visible message anchor with one coordinated settle loop", () => {
  assert.match(workspace, /handleLoadOlderHistory/);
  assert.match(workspace, /messageHistoryAnchorRef/);
  assert.match(workspace, /captureVisibleMessageAnchor/);
  assert.match(workspace, /preserveOlderHistoryAnchor/);
  assert.match(workspace, /cancelScheduledMessageScroll/);
  assert.match(workspace, /MESSAGE_ANCHOR_SELECTOR/);
  assert.match(workspace, /getBoundingClientRect\(\)\s*\.top/);
  assert.match(workspace, /data-message-id/);
  assert.match(workspace, /const delta =\s*nextTop - anchor\.top/s);
  assert.match(workspace, /scrollNode\.scrollTop \+= delta/);
  assert.match(workspace, /fallbackApplied/);
  assert.match(workspace, /MESSAGE_ANCHOR_TOLERANCE_PX = 1/);
  assert.match(workspace, /MESSAGE_ANCHOR_STABLE_FRAMES = 3/);
  assert.match(workspace, /MESSAGE_ANCHOR_MAX_SETTLE_FRAMES = 120/);
  assert.match(workspace, /MESSAGE_ANCHOR_QUIET_MS = 120/);
  assert.match(workspace, /MESSAGE_ANCHOR_MAX_SETTLE_MS = 2000/);
  assert.match(workspace, /scheduleOlderHistoryAnchorSettlement/);
  assert.match(workspace, /markOlderHistoryAnchorDirty/);
  assert.match(workspace, /anchor\.stableFrames/);
  assert.match(workspace, /anchor\.settleFrames/);
  assert.match(workspace, /anchor\.lastMutationAt/);
  assert.match(workspace, /shouldAutoFollowMessagesRef\.current = false/);
  assert.match(workspace, /messageHistoryAnchorRef\.current != null/);
  assert.match(workspaceCss, /\.workspace-scroll\s*\{[\s\S]*?overflow-anchor:\s*none;/);
  assert.match(workspace, /onLoadOlderHistory=\{handleLoadOlderHistory\}/);

  const observerStart = workspace.indexOf("const observer = new ResizeObserver");
  assert.ok(observerStart >= 0, "ResizeObserver must be present");
  const observerEnd = workspace.indexOf("observer.observe(contentNode)", observerStart);
  assert.ok(observerEnd > observerStart, "ResizeObserver block must be present");
  const observerBlock = workspace.slice(observerStart, observerEnd);
  assert.match(observerBlock, /markOlderHistoryAnchorDirty\(\)/);
  assert.doesNotMatch(
    observerBlock,
    /preserveOlderHistoryAnchor\(\)/,
    "ResizeObserver must not independently write the message anchor",
  );
});




test("same-conversation refresh preserves an already expanded durable history window", () => {
  assert.match(app, /mergeLatestMessagePage/);
  assert.match(app, /overlapsExistingWindow/);
  assert.match(app, /hasMore:\s*projection\.hasMore/);
  assert.match(app, /nextBeforeId:\s*projection\.nextBeforeId/);
  assert.match(app, /mergeMessageRows\(projection\.items,\s*page\.items\)/);
});

test("Conversation Reliability browser durability makes concrete anchor displacement authoritative and redacts QA codes", () => {
  assert.match(v41Browser, /durableMessageSnapshot/);
  assert.match(v41Browser, /getBoundingClientRect\(\)\.top/);
  assert.match(v41Browser, /hasConcreteAnchor/);
  assert.match(v41Browser, /anchorDisplacement <= 16/);
  assert.match(v41Browser, /anchorMode:\s*hasConcreteAnchor/s);
  assert.match(v41Browser, /redactQaDiagnostics/);
  assert.match(v41Browser, /\[REDACTED\]/);

  const concreteGate = v41Browser.indexOf("if (hasConcreteAnchor)");
  const fallbackGate = v41Browser.indexOf("scrollDisplacement <= 8", concreteGate);
  assert.ok(concreteGate >= 0, "concrete element gate must be present");
  assert.ok(fallbackGate > concreteGate, "height arithmetic must be fallback-only");
  assert.match(v41Browser, /conversationReliabilityHistoryEvidence/);
  assert.match(v41Browser, /initialHistoryEvidence\.count >= 125/);
  assert.match(v41Browser, /sameConversationEvidence\.firstMarker/);
  assert.match(v41Browser, /sameConversationEvidence\.lastMarker/);
  assert.match(v41Browser, /same-conversation refresh collapsed the expanded durable history window/);
  assert.match(v41Browser, /\[Conversation Reliability\] memory-capsule/);
  assert.match(v41Browser, /\[Conversation Reliability\] redis-working-memory/);
  assert.match(v41Browser, /\[Conversation Reliability\] redis-loss-recovery/);
});

test("Conversation Reliability canonical browser waits for the new-conversation control before clicking after reload", () => {
  const helperStart = v41Browser.indexOf("async function createConversationThroughBrowser");
  assert.ok(helperStart >= 0, "createConversationThroughBrowser helper must exist");
  const helperEnd = v41Browser.indexOf("async function openConversation", helperStart);
  assert.ok(helperEnd > helperStart, "createConversationThroughBrowser helper block must exist");
  const helperBlock = v41Browser.slice(helperStart, helperEnd);
  assert.match(helperBlock, /waitFor\(/);
  assert.match(helperBlock, /conversation-create/);
  assert.match(helperBlock, /new conversation button ready/);
  assert.match(helperBlock, /clickSelector\(cdp, '\[data-testid="conversation-create"\]'/);
});

test("Conversation Reliability canonical browser waits for a conversation rail item before opening it after reload", () => {
  const helperStart = v41Browser.indexOf("async function openConversation");
  assert.ok(helperStart >= 0, "openConversation helper must exist");
  const helperEnd = v41Browser.indexOf("async function assertConversationAtBottom", helperStart);
  assert.ok(helperEnd > helperStart, "openConversation helper block must exist");
  const helperBlock = v41Browser.slice(helperStart, helperEnd);
  assert.match(helperBlock, /waitFor\(/);
  assert.match(helperBlock, /conversation-item-\$\{id\}/);
  assert.match(helperBlock, /rail item ready/);
  assert.match(helperBlock, /clickSelector\(cdp, selector, `conversation \$\{id\}`\)/);
});

test("Conversation Reliability sendPrompt waits for this submission to become durable when no expected text is provided", () => {
  const helperStart = v41Browser.indexOf("async function sendPrompt");
  assert.ok(helperStart >= 0, "sendPrompt helper must exist");
  const helperEnd = v41Browser.indexOf("async function openLatestRunDetails", helperStart);
  assert.ok(helperEnd > helperStart, "sendPrompt helper block must exist");
  const helperBlock = v41Browser.slice(helperStart, helperEnd);

  assert.match(helperBlock, /durableAssistantCount/);
  assert.match(helperBlock, /promptPersisted/);
  assert.match(helperBlock, /assistants\.length > \$\{beforeSend\.durableAssistantCount\}/);
  assert.match(helperBlock, /durable assistant response for \$\{prompt\}/);
  assert.doesNotMatch(
    helperBlock,
    /waitFor\(cdp, `document\.querySelector\('\[data-testid="message-assistant"\]'\)`/,
    "sendPrompt must not treat a pre-existing assistant row as completion of the new submission",
  );
});

test("Conversation Reliability canonical real-stack closes browser, capsule, Redis-loss and internal-auth durability loop", () => {
  assert.match(v41Browser, /runConversationMemoryFixture\("seed-history"/);
  assert.match(v41Browser, /"--count", "125"/);
  assert.match(v41Browser, /loadAllConversationHistory\(cdp, 125\)/);
  assert.match(v41Browser, /waitForConversationCapsules/);
  assert.match(v41Browser, /missing internal token must be rejected/);
  assert.match(v41Browser, /wrong internal token must be rejected/);
  assert.match(v41Browser, /cross-user capsule access must fail closed/);
  assert.match(v41Browser, /same capsule range must upsert idempotently/);
  assert.match(v41Browser, /Runtime Redis working list exceeded 20 messages/);
  assert.match(v41Browser, /MySQL capsule disappeared after Redis clear/);
});

test("Conversation Reliability browser observes concrete anchor stability on animation frames without relaxing the displacement gate", () => {
  const helperStart = v41Browser.indexOf("async function waitForConcreteOlderHistoryAnchorSettlement");
  assert.ok(helperStart >= 0, "frame-based anchor settlement helper must exist");
  const helperEnd = v41Browser.indexOf("async function composerValue", helperStart);
  assert.ok(helperEnd > helperStart, "older-history helper block must exist");
  const helper = v41Browser.slice(helperStart, helperEnd);
  assert.match(helper, /requestAnimationFrame\(tick\)/);
  assert.match(helper, /new WheelEvent\('wheel'/);
  assert.match(helper, /Conversation Reliability reader intent did not hold the top viewport/);
  assert.match(helper, /node\.scrollTop=0/);
  assert.match(helper, /tolerancePx = 16/);
  assert.match(helper, /stableFramesRequired = 3/);
  assert.match(helper, /stableTopDeltaPx = 1/);
  assert.match(helper, /quietMsRequired = 600/);
  assert.match(helper, /lastGeometryChangeAt/);
  assert.match(helper, /historyLoading/);
  assert.match(helper, /quietFor >= quietMsRequired/);
  assert.match(helper, /stable-concrete-anchor-after-quiet-window/);
  assert.match(helper, /maxFrames = 150/);
  assert.match(helper, /maxWallMs = 10000/);
  assert.match(helper, /wallTimer=setTimeout/);
  assert.match(helper, /settlement\.settled/);
  assert.match(helper, /anchorDisplacement <= 16/);
  assert.doesNotMatch(helper, /Conversation Reliability concrete older-history anchor settlement",\s*5000/);
  assert.doesNotMatch(helper, /await sleep\(120\)/);

  assert.match(workspace, /anchor\.settleFrames >=\s*MESSAGE_ANCHOR_STABLE_FRAMES/);
});

test("Conversation Reliability Desktop shutdown captures listener ownership and fails closed on foreign PID reuse", () => {
  assert.match(v41Browser, /async function captureDesktopBridgeOwnership/);
  assert.match(v41Browser, /queryWindowsLoopbackListenerIdentities/);
  assert.match(v41Browser, /desktop\.__agentmeshQaDesktopOwnership = await captureDesktopBridgeOwnership/);
  assert.match(v41Browser, /listenerIdentityMatches/);
  assert.match(v41Browser, /desktopServerPids\(readProcessLog\(\)\)/);
  assert.match(v41Browser, /listener ownership could not be proven/);
  assert.match(v41Browser, /PID reuse must not turn an unrelated process into a QA-owned process/);
  assert.match(v41Browser, /Refusing to kill an unowned process/);
  assert.match(v41Browser, /startup listener ownership was not captured/);
  assert.match(v41Browser, /refusing to terminate an unverified PID/);
  assert.match(v41Browser, /child\.kill\("SIGTERM"\)/);
  assert.match(v41Browser, /taskkill", \["\/PID", String\(pid\), "\/F"\]/);
  assert.match(v41Browser, /Stop-Process -Id \${pid} -Force -ErrorAction Stop/);
  assert.doesNotMatch(v41Browser, /Stop-Process -Id \$_\.OwningProcess -Force/);
});

test("Conversation Reliability Desktop shutdown uses TCP closure as authority without a shorter outer timeout", () => {
  const helperStart = v41Browser.indexOf("async function stopDesktopBridge");
  assert.ok(helperStart >= 0, "Desktop shutdown helper must exist");
  const helperEnd = v41Browser.indexOf("async function closeBrowser", helperStart);
  assert.ok(helperEnd > helperStart, "Desktop shutdown helper boundary must exist");
  const helper = v41Browser.slice(helperStart, helperEnd);

  assert.match(helper, /stopOwnedLoopbackListener/);
  assert.match(helper, /loopbackPortAccepting/);
  assert.match(helper, /const deadline = Date\.now\(\) \+ 15000/);
  assert.match(helper, /Desktop Bridge still listening on its owned QA port/);
  assert.match(helper, /captured=/);
  assert.match(helper, /current=/);
  assert.doesNotMatch(v41Browser, /withTimeout\(stopDesktopBridge\(/);
});
