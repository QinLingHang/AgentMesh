import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const root = path.resolve(import.meta.dirname, "..");
const read = (relative) => fs.readFileSync(path.join(root, relative), "utf8");

test("Run Details exposes a dedicated P6 Eval scorecard", () => {
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

test("P6 scorecard contract contains metadata only and is reconstructable after refresh", () => {
  const types = read("src/types.ts");
  const historical = read("src/features/workspace/historicalRun.ts");

  assert.match(types, /export type RunScorecard/);
  assert.match(types, /failureCategory:\s*string/);
  assert.match(types, /violations:\s*string\[\]/);
  assert.doesNotMatch(types.slice(types.indexOf("export type RunScorecard"), types.indexOf("// =========================================================\n// Run / Resume Result")), /content:\s*string/);
  assert.match(historical, /normalizeScorecard/);
  assert.match(historical, /metadata\.scorecard/);
});

test("P6 exposes model cost and tool outcome telemetry", () => {
  const types = read("src/types.ts");
  const overview = read("src/features/run-details/EvalScorecardPanel.tsx");
  assert.match(types, /modelEstimatedCost:\s*number/);
  assert.match(types, /toolSuccesses:\s*number/);
  assert.match(types, /toolFailures:\s*number/);
  assert.match(overview, /Model Cost/);
  assert.match(overview, /Model Tokens/);
});
