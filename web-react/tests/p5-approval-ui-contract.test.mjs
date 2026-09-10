import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const root = path.resolve(import.meta.dirname, "..");
const read = (relative) => fs.readFileSync(path.join(root, relative), "utf8");

test("Tool approval uses explicit approve/reject controls instead of typed technical authorization", () => {
  const panel = read("src/features/workspace/ResumePanel.tsx");
  const api = read("src/api.ts");

  assert.match(panel, /需要你的确认/);
  assert.match(panel, /取消操作/);
  assert.match(panel, /确认执行/);
  assert.match(panel, /onApprovalDecision\("reject"\)/);
  assert.match(panel, /onApprovalDecision\("approve"\)/);
  assert.match(api, /export const decideTaskApproval/);
  assert.match(api, /JSON\.stringify\(\{\s*decision,/s);
});

test("Browser Task contract exposes only approval preview and never authoritative continuation", () => {
  const types = read("src/types.ts");
  assert.match(types, /export type TaskApproval/);
  assert.match(types, /argumentsPreview\?: Record<string, unknown>/);
  assert.doesNotMatch(types, /export type Task = \{[\s\S]*continuation\??:/);
});

test("Run Details Tool & MCP observability includes approval events", () => {
  const tabs = read("src/features/run-details/RunDetailsTabs.tsx");
  const panel = read("src/features/run-details/ToolMCPTracePanel.tsx");
  assert.match(tabs, /event\.kind === "approval"/);
  assert.match(panel, /event\.kind === "approval"/);
  assert.match(panel, /human approval/);
});

test("Workspace treats persisted task state as authoritative over stale approval snapshots", () => {
  const workspace = read("src/features/workspace/Workspace.tsx");
  assert.match(workspace, /persistedLatestRunTask/);
  assert.match(workspace, /persistedWaitingTask \?\?\s*latestWaitingTask/s);
  assert.match(workspace, /setLatestRunState\(null\)/);
  assert.match(workspace, /已刷新最新任务状态/);
});


test("Workspace binds approval UI to the newest task and newest turn in the conversation", () => {
  const workspace = read("src/features/workspace/Workspace.tsx");

  assert.match(workspace, /function latestTaskForConversation/);
  assert.match(workspace, /latestConversationTask\.id === latestRun\.task\.id/);
  assert.match(workspace, /submissionEpochByConversationRef/);
  assert.match(workspace, /isLatestSubmissionOwner/);
  assert.match(workspace, /approvalTask\.conversationId !== approvalConversationId/);
});

test("Older waiting approvals are not rendered after a newer conversation task exists", () => {
  const workspace = read("src/features/workspace/Workspace.tsx");

  assert.match(
    workspace,
    /const persistedWaitingTask =\s*latestConversationTask &&\s*isWaitingStatus\(\s*latestConversationTask\.status/s,
  );
  assert.doesNotMatch(
    workspace,
    /tasks\.find\(\s*\(task\) =>\s*task\.conversationId ===\s*current\.id &&\s*isWaitingStatus/s,
  );
});
