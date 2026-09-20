import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const root = path.resolve(import.meta.dirname, "..");
const read = (relative) => fs.readFileSync(path.join(root, relative), "utf8");

test("p37 harness mode setting group exists with the four contract modes", () => {
  const config = read("src/features/workspace/RunConfiguration.tsx");
  assert.match(config, /data-testid="harness-mode-select"/);
  assert.match(config, /value="OFF"/);
  assert.match(config, /value="OBSERVE"/);
  assert.match(config, /value="ENFORCE"/);
  assert.match(config, /value="AUTO_REPAIR"/);

  // 默认 OFF：不改变既有执行语义。
  const workspace = read("src/features/workspace/Workspace.tsx");
  assert.match(workspace, /useState<HarnessMode>\("OFF"\)/);
});

test("p37 AUTO_REPAIR budget fields are gated on the mode", () => {
  const config = read("src/features/workspace/RunConfiguration.tsx");
  // 高级预算折叠区只在非 OFF 模式出现
  assert.match(config, /harnessMode !== "OFF" && \(/);
  // 修复/重试预算只在 AUTO_REPAIR 展示
  assert.match(config, /harnessMode === "AUTO_REPAIR" && \(/);
  assert.match(config, /harnessMaxRepairs/);
  assert.match(config, /harnessMaxRetriesPerTool/);
  assert.match(config, /harnessMaxSteps/);
  assert.match(config, /harnessLoopRepeatThreshold/);
});

test("p37 harness config rides both runTask and runTaskStream request bodies", () => {
  const api = read("src/api.ts");
  assert.match(api, /harnessConfig\?: import\("\.\/types"\)\.HarnessConfig/);
  // 统一的请求体构造被两条链路复用，避免遗漏。
  assert.match(api, /function buildRunTaskBody/);
  assert.match(api, /body: buildRunTaskBody\(input\)/);
  const occurrences = (api.match(/buildRunTaskBody\(input\)/g) ?? []).length;
  assert.ok(occurrences >= 2, "runTask and runTaskStream must both send harnessConfig");
  // OFF 模式不上报 harness 字段，保持旧行为。
  const workspace = read("src/features/workspace/Workspace.tsx");
  assert.match(workspace, /harnessMode === "OFF"\s*\n?\s*\?\s*undefined/);
});

test("p37 harness detail tab is data-driven and hidden for legacy runs", () => {
  const tabs = read("src/features/run-details/RunDetailsTabs.tsx");
  assert.match(tabs, /"harness"/);
  assert.match(tabs, /result\.harnessSummary \|\| result\.harnessReport/);

  const details = read("src/features/run-details/RunDetails.tsx");
  assert.match(details, /HarnessTracePanel/);

  const panel = read("src/features/run-details/HarnessTracePanel.tsx");
  assert.match(panel, /状态时间线/);
  assert.match(panel, /失败诊断/);
  assert.match(panel, /恢复动作/);
  assert.match(panel, /预算消耗/);
  assert.doesNotMatch(panel, /dangerouslySetInnerHTML/);
});

test("p37 harness types keep the Python/Go contract field names", () => {
  const types = read("src/types.ts");
  assert.match(types, /export type HarnessMode = "OFF" \| "OBSERVE" \| "ENFORCE" \| "AUTO_REPAIR";/);
  assert.match(types, /export type HarnessSummary = \{/);
  assert.match(types, /export type HarnessReport = \{/);
  assert.match(types, /terminationReason\?/);
  assert.match(types, /recommendedAction\?/);
});

test("p37 agent form exposes executor type only for internal protocol", () => {
  const agents = read("src/features/agents/Agents.tsx");
  assert.match(agents, /agent-executor-type/);
  assert.match(agents, /value="openjiuwen"/);
  // 非 internal 协议强制回落 native。
  assert.match(agents, /next !== "internal"/);
});
