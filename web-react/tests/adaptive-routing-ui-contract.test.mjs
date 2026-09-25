import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const root = path.resolve(import.meta.dirname, "..");
const read = (relative) => fs.readFileSync(path.join(root, relative), "utf8");

test("Run Details exposes a dedicated Routing tab for Agent, Model and fallback decisions", () => {
  const tabs = read("src/features/run-details/RunDetailsTabs.tsx");
  const details = read("src/features/run-details/RunDetails.tsx");
  const panel = read("src/features/run-details/RoutingTracePanel.tsx");

  assert.match(tabs, /id:\s*"routing"/);
  assert.match(tabs, /label:\s*"Routing"/);
  assert.match(tabs, /event\.kind === "routing"/);
  assert.match(tabs, /event\.kind === "model_route"/);
  assert.match(tabs, /event\.kind === "reschedule"/);
  assert.match(details, /RoutingTracePanel/);
  assert.match(panel, /Routing Decisions/);
  assert.match(panel, /Selected/);
  assert.match(panel, /Score/);
  assert.match(panel, /Degraded/);
  assert.match(panel, /candidate\.quality/);
  assert.match(panel, /candidate\.reliability/);
  assert.match(panel, /candidate\.latencyMs/);
  assert.match(panel, /candidate\.avgCost/);
});

test("malformed Routing detail fails closed instead of rendering arbitrary raw text", () => {
  const panel = read("src/features/run-details/RoutingTracePanel.tsx");

  assert.match(panel, /catch\s*\{\s*return \{\};\s*\}/s);
  assert.match(panel, /parseDetail\(event\.detail\)/);
  assert.doesNotMatch(panel, />\s*\{event\.detail\}\s*</);
  assert.doesNotMatch(panel, /dangerouslySetInnerHTML/);
});

test("Routing panel is metadata-oriented and has no user-content rendering fields", () => {
  const panel = read("src/features/run-details/RoutingTracePanel.tsx");

  assert.doesNotMatch(panel, /detail\.task\b/);
  assert.doesNotMatch(panel, /detail\.prompt\b/);
  assert.doesNotMatch(panel, /detail\.memory(Content)?\b/i);
  assert.doesNotMatch(panel, /detail\.rag(Evidence)?\b/i);
  assert.doesNotMatch(panel, /detail\.tool(Result)?\b/i);
  assert.doesNotMatch(panel, /detail\.password\b/i);
  assert.doesNotMatch(panel, /detail\.token\b/i);
  assert.doesNotMatch(panel, /detail\.otp\b/i);
  assert.doesNotMatch(panel, /detail\.credential\b/i);
});
