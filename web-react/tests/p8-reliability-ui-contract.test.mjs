import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const root = path.resolve(import.meta.dirname, "..");
const read = (relative) => fs.readFileSync(path.join(root, relative), "utf8");

test("Workspace defaults to interactive direct delivery while retaining the durable reliability path", () => {
  const workspace = read("src/features/workspace/Workspace.tsx");
  const api = read("src/api.ts");
  const config = read("src/features/workspace/RunConfiguration.tsx");

  assert.match(workspace, /useState<DeliveryMode>\([\s\S]*?"direct"/);
  assert.match(api, /deliveryMode\??:\s*DeliveryMode/);
  assert.match(api, /\/api\/tasks\/run-durable/);
  assert.match(api, /\/api\/tasks\/run/);
  assert.match(config, /<option value="durable">\s*可靠队列 · 长任务/s);
  assert.match(config, /<option value="direct">\s*互动模式 · 更快响应/s);
});

test("Tasks surface queue health and allow cancel only for active durable tasks", () => {
  const tasks = read("src/features/tasks/Tasks.tsx");
  const api = read("src/api.ts");
  const types = read("src/types.ts");

  assert.match(types, /"QUEUED"/);
  assert.match(tasks, /getRuntimeReliability/);
  assert.match(tasks, /reliability\.queueDepth/);
  assert.match(tasks, /reliability\.availableWorkers/);
  assert.match(tasks, /reliability\.circuitOpenWorkers/);
  assert.match(tasks, /task\.deliveryMode === "durable"/);
  assert.match(tasks, /task\.status === "QUEUED"/);
  assert.match(tasks, /task\.status === "RUNNING"/);
  assert.match(tasks, /onCancelTask/);
  assert.match(api, /\/api\/tasks\/\$\{taskId\}\/cancel/);
  assert.match(api, /\/api\/runtime\/reliability/);
});

test("Run Details Reliability panel whitelists metadata and fails closed on malformed detail", () => {
  const tabs = read("src/features/run-details/RunDetailsTabs.tsx");
  const details = read("src/features/run-details/RunDetails.tsx");
  const panel = read("src/features/run-details/ReliabilityTracePanel.tsx");

  assert.match(tabs, /id:\s*"reliability"/);
  assert.match(tabs, /label:\s*"Reliability"/);
  assert.match(tabs, /event\.kind === "reliability"/);
  assert.match(details, /ReliabilityTracePanel/);
  assert.match(panel, /Runtime Reliability/);
  assert.match(panel, /record\.jobId/);
  assert.match(panel, /record\.executionId/);
  assert.match(panel, /record\.workerId/);
  assert.match(panel, /catch\s*\{\s*return \{\};\s*\}/s);
  assert.doesNotMatch(panel, />\s*\{event\.detail\}\s*</);
  assert.doesNotMatch(panel, /dangerouslySetInnerHTML/);
  assert.doesNotMatch(panel, /detail\.task\b/);
  assert.doesNotMatch(panel, /detail\.prompt\b/);
  assert.doesNotMatch(panel, /detail\.endpoint\b/);
  assert.doesNotMatch(panel, /detail\.password\b/i);
  assert.doesNotMatch(panel, /detail\.token\b/i);
  assert.doesNotMatch(panel, /detail\.otp\b/i);
});
