import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const webRoot = path.resolve(import.meta.dirname, "..");
const source = (...parts) => fs.readFileSync(path.join(webRoot, ...parts), "utf8");

test("V4.1 conversation message projection is owned by the active conversation", () => {
  const app = source("src", "App.tsx");

  assert.match(app, /messageProjection/);
  assert.match(app, /conversationId:\s*number \| null/);
  assert.match(app, /const messageLoadSequenceRef = useRef\(0\)/);
  assert.match(app, /const currentConversationIdRef = useRef<number \| null>\(current\?\.id \?\? null\)/);
  assert.match(app, /currentConversationIdRef\.current = current\?\.id \?\? null/);

  const loadStart = app.indexOf("const loadMessages =");
  const loadEnd = app.indexOf("const loadTasks =", loadStart);
  assert.ok(loadStart >= 0 && loadEnd > loadStart, "App.loadMessages block must be present");
  const loadBlock = app.slice(loadStart, loadEnd);

  assert.match(loadBlock, /currentConversationIdRef\.current !== id/);
  assert.match(loadBlock, /sequence !== messageLoadSequenceRef\.current/);
  assert.match(
    loadBlock,
    /setMessageProjection\(\(projection\)\s*=>\s*mergeLatestMessagePage\(/s,
  );

  // P20 FIX13+ preserves an already-expanded same-conversation history window
  // while allowing the newest authoritative page to refresh duplicate rows.
  assert.match(app, /function mergeLatestMessagePage/);
  assert.match(app, /hasMore:\s*projection\.hasMore/);
  assert.match(app, /nextBeforeId:\s*projection\.nextBeforeId/);
  assert.match(app, /mergeMessageRows\(projection\.items,\s*loaded\.items\)/);
  assert.match(
    app,
    /for \(const item of incoming\) \{\s*byId\.set\(item\.id, item\);\s*\}/s,
  );

  assert.match(app, /messageProjection\.conversationId === current\.id\s*\? messageProjection\.items\s*:\s*\[\]/s);
  assert.match(app, /messageProjection\.conversationId !== current\.id/);
  assert.match(app, /const messagesLoading =/);
});

test("V4.1 conversation switch clears transient UI state instead of leaking it", () => {
  const workspace = source("src", "features", "workspace", "Workspace.tsx");

  const boundaryComment = workspace.indexOf("A conversation boundary is also a composer/runtime boundary");
  assert.ok(boundaryComment >= 0, "conversation-boundary reset effect must be present");
  const boundaryBlock = workspace.slice(boundaryComment, workspace.indexOf("],", boundaryComment) + 2);

  for (const setter of [
    "setText(\"\")",
    "setPendingPrompt(\"\")",
    "setPendingAttachments([])",
    "setStreamingAnswer(\"\")",
    "setStreamingPhase(\"\")",
    "setResumeText(\"\")",
    "setError(\"\")",
  ]) {
    assert.ok(boundaryBlock.includes(setter), `missing boundary reset: ${setter}`);
  }
});

test("V4.1 late direct-stream writes remain owned by the submitting conversation", () => {
  const workspace = source("src", "features", "workspace", "Workspace.tsx");
  const runStart = workspace.indexOf("const run = async");
  const runEnd = workspace.indexOf("const resume = async", runStart);
  assert.ok(runStart >= 0 && runEnd > runStart, "Workspace.run block must be present");
  const runBlock = workspace.slice(runStart, runEnd);

  assert.match(workspace, /const activeConversationIdRef = useRef<number \| null>\(current\?\.id \?\? null\)/);
  assert.match(workspace, /activeConversationIdRef\.current = current\?\.id \?\? null/);
  assert.match(runBlock, /const submissionConversationId = conversation\.id/);
  assert.match(runBlock, /activeConversationIdRef\.current === submissionConversationId/);

  const deltaStart = runBlock.indexOf("onDelta:");
  const statusStart = runBlock.indexOf("onStatus:", deltaStart);
  assert.ok(deltaStart >= 0 && statusStart > deltaStart, "stream callbacks must be present");
  assert.match(runBlock.slice(deltaStart, statusStart), /if \(!isSubmissionConversationActive\(\)\) return/);
  assert.match(runBlock.slice(statusStart), /if \(!isSubmissionConversationActive\(\)\) return/);
  assert.match(runBlock, /reloadMessages\(submissionConversationId\)/);
});
