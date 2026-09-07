import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const app = fs.readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
const workspace = fs.readFileSync(new URL("../src/features/workspace/Workspace.tsx", import.meta.url), "utf8");
const settings = fs.readFileSync(new URL("../src/features/model-settings/ModelSettings.tsx", import.meta.url), "utf8");
const api = fs.readFileSync(new URL("../src/api.ts", import.meta.url), "utf8");

test("v4.5 composer starts empty", () => {
  assert.match(workspace, /const \[text, setText\] = useState\(""\)/);
  assert.doesNotMatch(workspace, /分析这份数据，并总结其中的统计特征/);
});

test("v4.5 exposes personal model settings", () => {
  assert.match(app, /模型设置/);
  assert.match(app, /model-settings/);
  assert.match(settings, /个人大模型 Provider/);
  assert.match(settings, /API Key/);
  assert.match(settings, /maskedHint/);
});

test("v4.5 browser never reads API key plaintext", () => {
  assert.match(api, /getUserModelProvider/);
  assert.match(api, /upsertUserModelProvider/);
  assert.match(api, /deleteUserModelProvider/);
  assert.doesNotMatch(api, /getUserModelApiKey|readUserModelSecret|decryptUserModel/);
});
