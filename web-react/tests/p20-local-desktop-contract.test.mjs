import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const desktopConfig = fs.readFileSync(
  new URL("../../desktop-bridge/desktop_bridge/config.py", import.meta.url),
  "utf8",
);
const desktopPolicy = fs.readFileSync(
  new URL("../../desktop-bridge/desktop_bridge/policy.py", import.meta.url),
  "utf8",
);
const desktopApp = fs.readFileSync(
  new URL("../../desktop-bridge/desktop_bridge/app.py", import.meta.url),
  "utf8",
);
const runtimeDesktop = fs.readFileSync(
  new URL("../../runtime-python/app/tools/desktop.py", import.meta.url),
  "utf8",
);
const goConfig = fs.readFileSync(
  new URL("../../backend-go/internal/config/config.go", import.meta.url),
  "utf8",
);

test("P20 Go local environment loads nearest .env.local without replacing real env", () => {
  assert.match(goConfig, /loadLocalEnvironment\(\)/);
  assert.match(goConfig, /AGENTMESH_ENV_FILE/);
  assert.match(goConfig, /\.env\.local/);
  assert.match(goConfig, /godotenv\.Load\(candidate\)/);
  assert.doesNotMatch(goConfig, /godotenv\.Overload/);
});

test("P20 Desktop defaults to Local Computer Mode while preserving Restricted Mode", () => {
  assert.match(desktopConfig, /DESKTOP_ACCESS_MODE/);
  assert.match(desktopConfig, /"local"/);
  assert.match(desktopConfig, /"restricted"/);
  assert.match(desktopConfig, /GetDriveTypeW/);
  assert.match(desktopConfig, /DRIVE_FIXED == 3/);
  assert.match(desktopConfig, /legacy_roots/);
  assert.match(desktopConfig, /mode = "restricted"/);
  assert.match(desktopPolicy, /application-private path is protected in Local Computer Mode/);
  assert.match(desktopPolicy, /sensitive path requires explicit Restricted Mode allowSensitive permission/);
  assert.match(desktopApp, /"accessMode": settings\.access_mode/);
});

test("P20 Desktop read tools describe normal local-computer access, while mutations remain approval-gated", () => {
  assert.match(runtimeDesktop, /local\.fs\.list[\s\S]*List files and folders on the local computer/);
  assert.match(runtimeDesktop, /local\.fs\.read[\s\S]*Read a normal local text file directly/);
  assert.match(runtimeDesktop, /local\.fs\.write[\s\S]*"medium", True/);
  assert.match(runtimeDesktop, /local\.fs\.move[\s\S]*"high", True/);
  assert.match(runtimeDesktop, /local\.fs\.delete[\s\S]*"high", True/);
});
