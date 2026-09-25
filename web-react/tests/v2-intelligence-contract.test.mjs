import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const root = path.resolve(import.meta.dirname, "..");
const read = (relative) => fs.readFileSync(path.join(root, relative), "utf8");

test("V2 knowledge UI exposes multimodal ingestion state", () => {
  const types = read("src/types.ts");
  const knowledge = read("src/features/knowledge/KnowledgeCenter.tsx");

  for (const token of ["textChunkCount", "visualEvidenceCount", "pageCount", "visualStatus", "visualErrorMessage"]) {
    assert.match(types, new RegExp(token));
    assert.match(knowledge, new RegExp(token));
  }
  assert.match(knowledge, /\.png/);
  assert.match(knowledge, /\.webp/);
});

test("V2 Run Details exposes TEXT VISUAL HYBRID retrieval evidence", () => {
  const rag = read("src/features/run-details/RAGTracePanel.tsx");
  const types = read("src/types.ts");

  for (const token of ["retrievalMode", "ragTextCandidates", "ragVisualCandidates", "pageNumber", "visualType", "assetId"]) {
    assert.match(types, new RegExp(token));
  }
  for (const token of ["Retrieval Mode", "textCandidates", "visualCandidates", "pageNumber", "visualType", "已选多模态证据"]) {
    assert.match(rag, new RegExp(token));
  }
});

test("V2 evaluation UI exposes advanced deterministic score dimensions", () => {
  const panel = read("src/features/run-details/EvalScorecardPanel.tsx");
  const types = read("src/types.ts");

  for (const token of ["correctness", "citationQuality", "taskCompletion", "judgeReason"]) {
    assert.match(types, new RegExp(token));
    assert.match(panel, new RegExp(token));
  }
  assert.match(panel, /正确性/);
  assert.match(panel, /引用质量/);
});

test("V2 usage and cost API plus UI are wired without secret reads", () => {
  const api = read("src/api.ts");
  const types = read("src/types.ts");
  const overview = read("src/features/run-details/OverviewMetricGrid.tsx");
  const governance = read("src/features/governance/Governance.tsx");

  assert.match(types, /export type RunCostRecord/);
  assert.match(types, /export type CostSummary/);
  assert.match(api, /getUserCostSummary/);
  assert.match(api, /getProjectCostSummary/);
  assert.match(api, /getRunCost/);
  assert.match(api, /provider/);
  assert.match(api, /model/);
  assert.match(overview, /Token Model Cost/);
  assert.match(overview, /价格未配置/);
  assert.match(overview, /工具调用 \/ MCP 事件/);
  assert.match(overview, /RAG Latency/);
  assert.match(governance, /V2 Runtime 成本分析/);
  assert.doesNotMatch(api, /decrypt.*cost|secret.*cost/i);
});

test("V2 deterministic browser acceptance is wired and browser suite uses current Chinese navigation", () => {
  const pkg = JSON.parse(read("package.json"));
  const v2e2e = read("e2e/v2-intelligence-browser-e2e.mjs");
  const p11e2e = read("e2e/browser-e2e.mjs");
  const p12e2e = read("e2e/dev-session-restore.mjs");

  assert.equal(pkg.scripts["test:e2e:v2"], "node e2e/v2-intelligence-browser-e2e.mjs");
  for (const token of ["v2-architecture.png", "图片 2 张", "HYBRID", "已选多模态证据", "引用质量", "MODEL COST"]) {
    assert.match(v2e2e, new RegExp(token));
  }
  assert.match(p11e2e, /assertPage\(cdp, "能力中心", "让 AgentMesh 做得更多"\)/);
  assert.match(p11e2e, /assertPage\(cdp, "任务记录", "任务"\)/);
  assert.match(p11e2e, /workspace-breadcrumb span/);
  assert.doesNotMatch(p11e2e, /assertPage\(cdp, "扩展能力", "扩展能力"\)/);
  assert.match(v2e2e, /workspace-breadcrumb span/);
  assert.doesNotMatch(v2e2e, /workspace-title[^\n]*工作台/);
  assert.match(v2e2e, /citation-source-summary/);
  assert.match(v2e2e, /citation-source-details/);
  assert.match(v2e2e, /innerText\.toUpperCase\(\)/);
  assert.match(v2e2e, /RETRIEVAL MODE/);
  assert.match(v2e2e, /MOCK-V2-VISION/);
  assert.match(v2e2e, /\$0\.0042/);
  assert.doesNotMatch(v2e2e, /innerText\.includes\("Model Cost"\)/);
  assert.match(v2e2e, /V2-ARCHITECTURE\.PNG/);
  assert.match(v2e2e, /ARCHITECTURE/);
  assert.doesNotMatch(v2e2e, /button\[aria-label\^="查看引用 \[1\]"\]/);
  assert.match(p12e2e, /Promise\.race/);
  assert.match(p12e2e, /closeBrowser/);
});
