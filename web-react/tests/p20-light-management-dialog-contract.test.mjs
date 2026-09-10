import fs from "node:fs";
import test from "node:test";
import assert from "node:assert/strict";

const style = fs.readFileSync(new URL("../src/components/common/lightDialogControlStyle.ts", import.meta.url), "utf8");
const sessionRail = fs.readFileSync(new URL("../src/features/workspace/SessionRail.tsx", import.meta.url), "utf8");
const projectHome = fs.readFileSync(new URL("../src/features/workspace/ProjectHome.tsx", import.meta.url), "utf8");
const knowledge = fs.readFileSync(new URL("../src/features/knowledge/KnowledgeCenter.tsx", import.meta.url), "utf8");

test("workspace project-management dialogs keep editable controls on the light surface", () => {
  assert.match(style, /backgroundColor:\s*"#ffffff"/);
  assert.match(style, /colorScheme:\s*"light"/);
  assert.ok((sessionRail.match(/style=\{lightDialogControlStyle\}/g) ?? []).length >= 3);
  assert.ok((projectHome.match(/style=\{lightDialogControlStyle\}/g) ?? []).length >= 2);
  assert.ok((knowledge.match(/style=\{lightDialogControlStyle\}/g) ?? []).length >= 4);
});

test("management-dialog light override is imported after legacy themes and uses important light controls", () => {
  const app = fs.readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
  const css = fs.readFileSync(new URL("../src/styles/p20-light-management-dialog.css", import.meta.url), "utf8");

  const legacyImport = app.indexOf('import "./styles/theme-v4-6-chinese-light.css";');
  const guardImport = app.indexOf('import "./styles/p20-light-management-dialog.css";');
  assert.ok(legacyImport >= 0, "expected final legacy theme import");
  assert.ok(guardImport > legacyImport, "light dialog guard must load after legacy theme layers");

  assert.match(css, /\.workspace-management-dialog \.field input/);
  assert.match(css, /background(?:-color)?:\s*#ffffff\s*!important/);
  assert.match(css, /color-scheme:\s*light\s*!important/);
  assert.match(css, /-webkit-text-fill-color:\s*#24312e\s*!important/);
});
