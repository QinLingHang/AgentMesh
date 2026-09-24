import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const root = path.resolve(import.meta.dirname, "..");
const read = (relative) => fs.readFileSync(path.join(root, relative), "utf8");

test("Execution Routing case56 keeps request-local attachment IDs in the single accepted submit", () => {
  const workspace = read("src/features/workspace/Workspace.tsx");
  assert.match(workspace, /const submittedAttachments = readyAttachments\.slice\(\)/);
  assert.match(workspace, /attachmentIds:\s*submittedAttachments\.map\(\(item\) => item\.server!\.id\)/);
  assert.match(workspace, /Exactly one submit request/);
  assert.doesNotMatch(workspace, /preflight.*fetch.*runTaskStream/is);
});

test("Execution Routing case72 exposes an explicit reject control bound to the approval decision API", () => {
  const panel = read("src/features/workspace/ResumePanel.tsx");
  assert.match(panel, /onApprovalDecision\("reject"\)/);
  assert.match(panel, /data-testid="approval-reject"/);
  assert.match(panel, /取消操作/);
  assert.match(panel, /确认只对上面这一次具体操作有效/);
});

test("Execution Routing case82 UI does not equate delete governance with disabling all tools", () => {
  const tools = read("src/features/extensions/ToolsPanel.tsx");
  // Tool deletion in the management panel is an explicit administrative action;
  // runtime read tools remain represented individually rather than through one
  // global 'tools disabled' switch.
  assert.match(tools, /deleteTool\(tool\.id\)/);
  assert.doesNotMatch(tools, /disableAllTools|blockAllTools|forbidAllTools/);
});

test("Execution Routing focused case56 keeps interactive delivery independent of Durable configuration", () => {
  const harness = read("e2e/v4-1-browser-e2e.mjs");
  assert.match(harness, /DURABLE_RUNTIME_ENABLED:\s*process\.env\.V4_1_E2E_ROUTING_REAL_STACK_ONLY\s*===\s*"true"\s*\?\s*"true"\s*:\s*"false"/);
  assert.match(harness, /const constraints = options\.constraints \|\| \{ maxLatencyMs: 8000,/);
  assert.match(harness, /assert\.equal\(route56\?\.mode,\s*"direct"/);
  assert.match(harness, /case56 actual model context was missing document bytes/);
});

test("Desktop Bridge degradation asserts the real listener is gone in focused and full Chrome", () => {
  const harness = read("e2e/v4-1-browser-e2e.mjs");
  assert.match(harness, /async function stopDesktopBridge\(child, port, processLog\)/);
  assert.match(harness, /await stopOwnedLoopbackListener\(port, processLog\)/);
  assert.match(harness, /loopbackPortAccepting\(port\)/);
  assert.doesNotMatch(harness, /await stopChild\(desktop\)/);
  assert.match(harness, /desktopShutdownVerified = true/);
});


test("Execution Routing Case82 fixture follows selected delete capability and proves model selection before Approval", () => {
  const harness = read("e2e/v4-1-browser-e2e.mjs");
  const policy = read("e2e/desktop-tool-fixture-policy.mjs");
  assert.match(harness, /selectDesktopFixtureTool\(messages, tools\)/);
  assert.doesNotMatch(harness, /hasDesktopDelete && !toolMessage && \/删除\|delete\/i/);
  assert.match(policy, /names\.has\("local\.fs\.delete"\)/);
  assert.match(policy, /currentTurnToolMessage\(messages\)/);
  assert.match(harness, /toolNames:\s*Array\.isArray\(body\.tools\)/);
  assert.match(harness, /fixtureToolCalls/);
  assert.match(harness, /async function waitForModelToolExposure/);
  assert.match(harness, /Case 82 precondition: Desktop contract is partial and missing local\.fs\.delete/);
  assert.match(harness, /authoritative ToolLoop fixture did not finish sending local\.fs\.delete/);
  assert.match(harness, /authoritativeToolLoop:\s*isAuthoritativeToolLoopRequest\(messages\)/);
  assert.match(harness, /row\?\.authoritativeToolLoop === true/);
  assert.match(harness, /row\?\.responseFinished === true/);
  assert.match(harness, /local\.fs\.delete riskLevel is not high/);
  assert.match(harness, /local\.fs\.delete does not require confirmation/);
  assert.match(harness, /approvalTask82\?\.approval\?\.toolName === "local\.fs\.delete"/);
  assert.match(harness, /delete task AUTH_REQUIRED projection is missing local\.fs\.delete approval/);

  const exposureIndex = harness.indexOf("const deleteExposure = await waitForModelToolExposure");
  const selectionIndex = harness.indexOf("const deleteSelectionDeadline", exposureIndex);
  const approvalIndex = harness.indexOf('"delete approval card"', selectionIndex);
  assert.ok(exposureIndex >= 0 && selectionIndex > exposureIndex && approvalIndex > selectionIndex,
    "Case 82 must prove exposure and fixture Tool selection before waiting for Approval UI");
  assert.match(harness, /data-testid=\"approval-reject\"/);
  assert.doesNotMatch(harness, /textContent\?\.includes\(\'取消操作\'\)/);
});

test("Execution Routing focused browser proves ENABLED to OFF restart replay reuses one Durable task", () => {
  const harness = read("e2e/v4-1-browser-e2e.mjs");
  assert.match(harness, /spawnGoServer\("OFF"\)/);
  assert.match(harness, /idempotent_replay/);
  assert.match(harness, /G12 restart replay created a second task/);
  assert.match(harness, /G12 OFF replay re-executed model\/runtime work/);
});

test("Desktop Bridge shutdown retries the owned listener instead of trusting launcher exit", () => {
  const harness = read("e2e/v4-1-browser-e2e.mjs");
  assert.match(harness, /const deadline = Date\.now\(\) \+ 30000/);
  assert.match(harness, /await stopOwnedLoopbackListener\(port, processLog\)/);
  assert.match(harness, /after repeated owned-listener shutdown/);
});
