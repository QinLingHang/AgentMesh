import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const root = path.resolve(import.meta.dirname, "..");
const read = (relative) => fs.readFileSync(path.join(root, relative), "utf8");

test("v4.2 loads Soft Paper after prior theme layers", () => {
  const app = read("src/App.tsx");
  const oldTheme = app.indexOf('import "./styles/theme-v4-1.css"');
  const softPaper = app.indexOf('import "./styles/theme-v4-2-soft-light.css"');
  assert.ok(oldTheme >= 0);
  assert.ok(softPaper > oldTheme);
});

test("v4.2 interactive workspace defaults to direct but retains durable queue", () => {
  const workspace = read("src/features/workspace/Workspace.tsx");
  const config = read("src/features/workspace/RunConfiguration.tsx");
  assert.match(workspace, /useState<DeliveryMode>\([\s\S]*?"direct"/);
  assert.match(config, /value="direct"/);
  assert.match(config, /互动模式 · 更快响应/);
  assert.match(config, /value="durable"/);
  assert.match(config, /可靠队列 · 长任务/);
});

test("v4.2 Soft Paper removes dark markdown table luminance spikes", () => {
  const theme = read("src/styles/theme-v4-2-soft-light.css");
  assert.match(theme, /\.markdown-answer th[\s\S]*?background:\s*#eef1ee\s*!important/);
  assert.match(theme, /\.markdown-answer td[\s\S]*?background:\s*#ffffff\s*!important/);
  assert.match(theme, /content-visibility:\s*auto/);
});

test("v4.2 keeps request-local attachment UX in the workspace", () => {
  const workspace = read("src/features/workspace/Workspace.tsx");
  const strip = read("src/features/workspace/AttachmentStrip.tsx");
  assert.match(strip, /添加图片或文件/);
  assert.match(workspace, /onPaste/);
  assert.match(workspace, /onDrop/);
  assert.match(workspace, /uploadConversationAttachment/);
});
