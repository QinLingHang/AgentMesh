import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const root = path.resolve(import.meta.dirname, "..");
const read = (relative) => fs.readFileSync(path.join(root, relative), "utf8");

test("Run Details exposes a dedicated Tool & MCP observability tab", () => {
  const tabs = read("src/features/run-details/RunDetailsTabs.tsx");
  const details = read("src/features/run-details/RunDetails.tsx");
  const panel = read("src/features/run-details/ToolMCPTracePanel.tsx");

  assert.match(tabs, /"tool-mcp"/);
  assert.match(tabs, /Tool & MCP/);
  assert.match(details, /ToolMCPTracePanel/);
  assert.match(panel, /event\.kind === "tool"/);
  assert.match(panel, /event\.kind === "mcp"/);
  assert.doesNotMatch(panel, /detail\.result/);
});

test("MCP panel documents the real local demo server command", () => {
  const panel = read("src/features/extensions/MCPPanel.tsx");
  assert.match(panel, /python -m app\.mcp\.demo_server/);
  assert.match(panel, /127\.0\.0\.1:9583\/mcp/);
});


test("Tools panel supports real HTTP Tool registration", () => {
  const panel = read("src/features/extensions/ToolsPanel.tsx");
  const api = read("src/api.ts");
  assert.match(panel, /添加 HTTP Tool/);
  assert.match(panel, /app\.tools\.http_demo_server/);
  assert.match(api, /export const createTool/);
});
