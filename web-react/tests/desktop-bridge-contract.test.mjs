import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const api = fs.readFileSync(new URL("../src/api.ts", import.meta.url), "utf8");
const app = fs.readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
const toolsPanel = fs.readFileSync(
  new URL("../src/features/extensions/ToolsPanel.tsx", import.meta.url),
  "utf8",
);
const runTabs = fs.readFileSync(
  new URL("../src/features/run-details/RunDetailsTabs.tsx", import.meta.url),
  "utf8",
);
const desktopTrace = fs.readFileSync(
  new URL("../src/features/run-details/DesktopTracePanel.tsx", import.meta.url),
  "utf8",
);

test("desktop bridge tool seeding and update APIs are exposed", () => {
  assert.match(api, /seedDesktopTools/);
  assert.match(api, /\/api\/tools\/seed-desktop/);
  assert.match(api, /updateTool/);
  assert.match(api, /method:\s*"PATCH"/);
});


test("Desktop Agent official local tools auto-provision with authenticated shell load", () => {
  assert.match(app, /seedDesktopTools/);
  assert.match(app, /const bootstrapTools/);
  assert.match(
    app,
    /await seedDesktopTools\(\);[\s\S]*await loadTools\(\)/,
  );
  assert.match(app, /bootstrapTools\(\)/);
});

test("tools panel exposes complete Desktop Agent families without delete UI for official local tools", () => {
  assert.match(toolsPanel, /Desktop Agent · 本机能力/);
  assert.doesNotMatch(toolsPanel, /接入本机能力/);
  assert.match(toolsPanel, /已内置/);
  assert.match(toolsPanel, /重新同步/);
  assert.match(toolsPanel, /无需手动/);
  assert.match(toolsPanel, /local\.fs\./);
  assert.match(toolsPanel, /local\.app\./);
  assert.match(toolsPanel, /local\.tool\./);
  assert.match(toolsPanel, /local\.terminal\./);
  assert.match(toolsPanel, /local\.ui\./);
  assert.match(toolsPanel, /toggleDesktopTool/);
  assert.match(toolsPanel, /高级终端默认关闭/);
  assert.match(toolsPanel, /Computer Use/);
  assert.match(toolsPanel, /停用/);
  assert.match(toolsPanel, /启用/);
});

test("Run Details exposes metadata-only local desktop execution observability", () => {
  assert.match(runTabs, /id:\s*"desktop"/);
  assert.match(runTabs, /label:\s*"本机执行"/);
  assert.match(desktopTrace, /文件正文、截图 Base64、键入文本、终端命令和进程输出不会在这里展开/);
  assert.match(desktopTrace, /startsWith\("local\."\)/);
});
