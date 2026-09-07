import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import ts from "../node_modules/typescript/lib/typescript.js";

const root = path.resolve(import.meta.dirname, "..");
const read = (name) => fs.readFileSync(path.join(root, name), "utf8");

const app = read("src/App.tsx");
const api = read("src/api.ts");
const tabs = read("src/features/run-details/RunDetailsTabs.tsx");
const details = read("src/features/run-details/RunDetails.tsx");
const panel = read("src/features/run-details/MemoryTracePanel.tsx");
const timeline = read("src/features/run-details/ExecutionTimeline.tsx");
const format = read("src/utils/format.ts");

function compileFormatter() {
  const compiled = ts.transpileModule(format, {
    compilerOptions: {
      module: ts.ModuleKind.ESNext,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText;
  return import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);
}

const traceEvent = (kind, detail) => ({
  kind,
  detail,
  status: "completed",
  title: kind,
  elapsedMs: 1,
});

test("Memory is an implicit capability, not a primary navigation page", () => {
  assert.doesNotMatch(app, /id:\s*"memory"/);
  assert.doesNotMatch(app, /<MemoryCenter/);
  assert.doesNotMatch(app, /label:\s*"长期记忆"/);

  // The authenticated CRUD contract remains available for future Settings /
  // account tooling, but it is not exposed as a workspace module.
  assert.match(api, /request<UserMemory\[\]>\(\s*`\/api\/memories/);
  assert.match(api, /request<UserMemory>\(\s*"\/api\/memories"/);
  const memoryApiSlice = api.slice(
    api.indexOf("// User-global Long-term Memory"),
    api.indexOf("// Agent"),
  );
  assert.doesNotMatch(memoryApiSlice, /projectId/);
});

test("Run Details keeps developer-facing Memory observability including forget", () => {
  assert.match(tabs, /id:\s*"memory"/);
  for (const kind of ["memory_retrieval", "memory_write", "memory_forget"]) {
    assert.match(tabs, new RegExp(kind));
    assert.match(panel, new RegExp(kind));
  }
  assert.match(details, /<MemoryTracePanel/);
  assert.doesNotMatch(panel, /event\.detail\s*}/);
  assert.match(panel, /parseDetail/);
  assert.match(panel, /不展开原始内容|非结构化/);
  assert.match(timeline, /prettyTraceDetail\(/);
});

test("generic Trace view sanitizes all Memory details", async () => {
  const formatter = await compileFormatter();

  const write = formatter.prettyTraceDetail(traceEvent("memory_write", JSON.stringify({
    reason: "candidate",
    candidateCount: 1,
    extractor: "rule",
    content: "secret-value",
    writes: [{
      action: "created",
      memoryId: 4,
      memoryKey: "preference.code",
      category: "preference",
      content: "secret-value",
    }],
  })));
  assert.doesNotMatch(write, /secret-value|"content"/);

  const retrieval = formatter.prettyTraceDetail(traceEvent("memory_retrieval", JSON.stringify({
    reason: "memories_retrieved",
    candidateCount: 2,
    selectedCount: 1,
    unsafeSkippedCount: 1,
    semanticUsed: true,
    password: "pw-value",
    memories: [{
      memoryId: 5,
      memoryKey: "preference.lang",
      category: "preference",
      sourceType: "manual",
      score: 0.9,
      secret: "nested-secret",
    }],
  })));
  assert.doesNotMatch(retrieval, /pw-value|nested-secret|password|secret/);

  const forget = formatter.prettyTraceDetail(traceEvent("memory_forget", JSON.stringify({
    reason: "memory_forgotten",
    requested: true,
    deletedCount: 1,
    content: "do-not-show",
    deletes: [{
      memoryId: 5,
      memoryKey: "preference.lang",
      category: "preference",
      content: "do-not-show",
    }],
  })));
  assert.doesNotMatch(forget, /do-not-show|"content"/);
  assert.match(forget, /memoryKey/);
  assert.match(forget, /deletedCount/);

  for (const kind of ["memory_write", "memory_retrieval", "memory_forget"]) {
    const malformed = formatter.prettyTraceDetail(traceEvent(kind, "password=secret-value"));
    assert.equal(
      malformed,
      "[Memory Trace detail hidden: only approved metadata is shown for privacy.]",
    );
  }

  assert.equal(
    formatter.prettyTraceDetail(traceEvent("tool", "malformed legacy detail")),
    "malformed legacy detail",
  );
});
