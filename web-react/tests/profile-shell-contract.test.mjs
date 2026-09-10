import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const app = fs.readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
const profile = fs.readFileSync(new URL("../src/features/profile/Profile.tsx", import.meta.url), "utf8");
const workspace = fs.readFileSync(new URL("../src/features/workspace/Workspace.tsx", import.meta.url), "utf8");

test("global shell removes redundant start-new-task action and exposes profile from the user footer", () => {
  assert.doesNotMatch(app, /开始新任务/);
  assert.doesNotMatch(app, /handleStartNewTask/);
  assert.match(app, /\|\s*"profile"/);
  assert.match(app, /data-testid="nav-profile"/);
  assert.match(app, /navigateToTab\("profile"\)/);
});

test("profile page uses only existing user and workspace data", () => {
  assert.match(profile, /个人主页/);
  assert.match(profile, /user\.displayName/);
  assert.match(profile, /user\.email/);
  assert.match(profile, /projects\.length/);
  assert.match(profile, /conversations\.length/);
  assert.match(profile, /agents\.length/);
  assert.match(profile, /tasks\.length/);
  assert.doesNotMatch(profile, /apiKey|token|password/i);
});

test("workspace keeps Enter submit, Shift+Enter newline, IME safety and newest-message landing", () => {
  assert.match(workspace, /e\.key\s*!==\s*"Enter"/);
  assert.match(workspace, /e\.shiftKey/);
  assert.match(workspace, /e\.nativeEvent\.isComposing/);
  assert.doesNotMatch(workspace, /Ctrl \/ ⌘ \+ Enter/);
  assert.match(workspace, /messageScrollRef/);
  assert.match(workspace, /scrollNode\.scrollHeight\s*-\s*scrollNode\.clientHeight/);
});
