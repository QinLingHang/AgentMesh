import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const root = path.resolve(import.meta.dirname, "..");
const read = (relative) => fs.readFileSync(path.join(root, relative), "utf8");

test("Run Details exposes a dedicated Evaluation Eval scorecard", () => {
  const tabs = read("src/features/run-details/RunDetailsTabs.tsx");
  const details = read("src/features/run-details/RunDetails.tsx");
  const panel = read("src/features/run-details/EvalScorecardPanel.tsx");
  const health = read("src/features/run-details/RunHealthPanel.tsx");

  assert.match(tabs, /id:\s*"eval"/);
  assert.match(tabs, /label:\s*"Eval"/);
  assert.match(details, /EvalScorecardPanel/);
  assert.match(panel, /Overall Score/);
  assert.match(panel, /Budget Compliance/);
  assert.match(panel, /Groundedness/);
  assert.match(panel, /Tool Reliability/);
  assert.match(panel, /RAG Quality/);
  assert.match(panel, /Memory Contribution/);
  assert.match(health, /scorecardWarning/);
  assert.match(health, /Eval \/ Policy/);
});

test("Evaluation scorecard contract contains metadata only and is reconstructable after refresh", () => {
  const types = read("src/types.ts");
  const historical = read("src/features/workspace/historicalRun.ts");

  assert.match(types, /export type RunScorecard/);
  assert.match(types, /failureCategory:\s*string/);
  assert.match(types, /violations:\s*string\[\]/);
  assert.doesNotMatch(types.slice(types.indexOf("export type RunScorecard"), types.indexOf("// =========================================================\n// Run / Resume Result")), /content:\s*string/);
  assert.match(historical, /normalizeScorecard/);
  assert.match(historical, /metadata\.scorecard/);
});

test("Evaluation exposes model cost and tool outcome telemetry", () => {
  const types = read("src/types.ts");
  const overview = read("src/features/run-details/EvalScorecardPanel.tsx");
  assert.match(types, /modelEstimatedCost:\s*number/);
  assert.match(types, /toolSuccesses:\s*number/);
  assert.match(types, /toolFailures:\s*number/);
  assert.match(overview, /Model Cost/);
  assert.match(overview, /Model Tokens/);
});

test("Run Details separates agent execution estimate from token-priced model cost", () => {
  const summary = read("src/features/run-details/RunSummaryStrip.tsx");
  const overview = read("src/features/run-details/OverviewMetricGrid.tsx");
  const tabs = read("src/features/run-details/RunDetailsTabs.tsx");

  assert.match(summary, /Agent 执行成本估算/);
  assert.match(summary, /不等于模型 Token 费用/);
  assert.match(overview, /Token Model Cost/);
  assert.match(tabs, /知识检索 · 事件/);
  assert.match(tabs, /长期记忆 · 事件/);
  assert.match(tabs, /工具\/MCP · 事件/);
});

