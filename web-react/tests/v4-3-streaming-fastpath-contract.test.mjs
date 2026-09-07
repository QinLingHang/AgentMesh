import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const root = path.resolve(import.meta.dirname, "..");
const read = (relative) => fs.readFileSync(path.join(root, relative), "utf8");

test("v4.3 clears the submitted composer immediately and preserves a new draft", () => {
  const workspace = read("src/features/workspace/Workspace.tsx");
  const clearIndex = workspace.indexOf('setText("");');
  const streamIndex = workspace.indexOf("await runTaskStream");
  assert.ok(clearIndex >= 0);
  assert.ok(streamIndex > clearIndex);
  assert.match(workspace, /placeholder=\{busy \? "可以继续输入下一条消息…"/);
});

test("v4.3 direct delivery uses a real fetch ReadableStream endpoint", () => {
  const api = read("src/api.ts");
  const workspace = read("src/features/workspace/Workspace.tsx");
  assert.match(api, /\/api\/tasks\/run-stream/);
  assert.match(api, /response\.body\.getReader\(\)/);
  assert.match(api, /event\.type === "delta"/);
  assert.match(workspace, /onDelta:\s*\(delta\)/);
});

test("v4.3 shows live streamed markdown instead of a fake post-hoc typewriter", () => {
  const history = read("src/features/workspace/MessageHistory.tsx");
  assert.doesNotMatch(history, /function ProgressiveAnswer/);
  assert.match(history, /assistant-streaming-answer/);
  assert.match(history, /CitationAnswer content=\{streamingAnswer\}/);
});
