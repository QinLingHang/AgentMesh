import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const governance = fs.readFileSync(new URL("../src/features/governance/Governance.tsx", import.meta.url), "utf8");
const api = fs.readFileSync(new URL("../src/api.ts", import.meta.url), "utf8");
const app = fs.readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");

test("Governance exposes governance without exposing secret plaintext reads", () => {
  assert.match(app, /治理与安全/);
  assert.match(governance, /保存后不可读取/);
  assert.match(governance, /maskedHint/);
  assert.doesNotMatch(api, /getProjectSecretValue|readProjectSecret|decryptProjectSecret/);
});

test("Governance governance UI covers RBAC quota BYOK and audit", () => {
  for (const token of ["OWNER", "ADMIN", "DEVELOPER", "VIEWER", "项目额度", "Project Model Provider", "审计日志"]) assert.match(governance, new RegExp(token));
});

test("Governance browser API only writes secret and never requests decrypted value", () => {
  assert.match(api, /createProjectSecret/);
  assert.match(api, /deleteProjectSecret/);
  assert.match(api, /upsertProjectModelProvider/);
  assert.doesNotMatch(api, /apiKey.*GET|secret.*plaintext/i);
});


test("Governance manual-preflight exposes organization operations and audit actor", () => {
  assert.match(api, /addOrganizationMember/);
  assert.match(api, /bindOrganizationProject/);
  assert.match(governance, /添加组织成员/);
  assert.match(governance, /绑定当前 Project 到组织/);
  assert.match(governance, /actorUserId/);
  assert.match(governance, /用户 #/);
});
