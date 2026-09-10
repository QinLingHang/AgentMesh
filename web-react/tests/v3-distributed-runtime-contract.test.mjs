import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import assert from "node:assert/strict";

const root = path.resolve(import.meta.dirname, "..");
const read = (relative) => fs.readFileSync(path.join(root, relative), "utf8");


test("V3 task page exposes multi-node topology without internal endpoints", () => {
  const tasks = read("src/features/tasks/Tasks.tsx");
  const overview = read("src/features/tasks/DistributedRuntimeOverview.tsx");
  const api = read("src/api.ts");
  const types = read("src/types.ts");

  assert.match(tasks, /getRuntimeTopology/);
  assert.match(tasks, /DistributedRuntimeOverview/);
  assert.match(overview, /多节点执行拓扑/);
  assert.match(overview, /调度器/);
  assert.match(overview, /工作节点调度状态/);
  assert.doesNotMatch(overview, /\.endpoint\b/);
  assert.match(api, /\/api\/runtime\/topology/);
  assert.match(types, /RuntimeTopologySnapshot/);
  assert.match(types, /schedulingScore/);
  assert.match(types, /dispatcherEpoch/);
});


test("V3 reliability trace carries node fencing and dispatcher epoch", () => {
  const panel = read("src/features/run-details/ReliabilityTracePanel.tsx");
  assert.match(panel, /nodeId/);
  assert.match(panel, /fenceEpoch/);
  assert.match(panel, /dispatcherEpoch/);
  assert.match(panel, /Node/);
  assert.match(panel, /Fence/);
  assert.match(panel, /Dispatcher/);
});


test("V3 durable run settings keep worker-loss replay opt-in", () => {
  const config = read("src/features/workspace/RunConfiguration.tsx");
  const drawer = read("src/features/workspace/RunSettingsDrawer.tsx");
  const workspace = read("src/features/workspace/Workspace.tsx");
  assert.match(config, /retryOnWorkerLoss/);
  assert.match(drawer, /Worker/);
  assert.match(workspace, /retryOnWorkerLoss/);
});


test("V3 distributed dashboard has dedicated styling", () => {
  const css = read("src/styles/tasks.css");
  assert.match(css, /distributed-runtime-overview/);
  assert.match(css, /runtime-topology-metrics/);
  assert.match(css, /runtime-node-card/);
  assert.match(css, /runtime-worker-table/);
});

test("V3 dedicated browser acceptance runner is wired", () => {
  const pkg = JSON.parse(read("package.json"));
  const e2e = read("e2e/v3-distributed-runtime-browser-e2e.mjs");
  assert.equal(pkg.scripts["test:e2e:v3"], "node e2e/v3-distributed-runtime-browser-e2e.mjs");
  assert.match(e2e, /V3 Deterministic Distributed Runtime Browser E2E: PASS/);
  assert.match(e2e, /node-a/);
  assert.match(e2e, /node-b/);
  assert.match(e2e, /调度纪元 8/);
  assert.match(e2e, /OFFLINE/);
});
