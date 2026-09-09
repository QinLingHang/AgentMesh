import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import assert from "node:assert/strict";

const root = path.resolve(import.meta.dirname, "..");
const projectRoot = path.resolve(root, "..");
const read = (relative) => fs.readFileSync(path.join(root, relative), "utf8");
const readProject = (relative) => fs.readFileSync(path.join(projectRoot, relative), "utf8");

test("V4 ecosystem center exposes marketplace, installations, API/SDK and publisher workflows", () => {
  const app = read("src/App.tsx");
  const page = read("src/features/ecosystem/Ecosystem.tsx");
  const api = read("src/api.ts");
  assert.match(app, /生态中心/);
  assert.match(app, /Ecosystem/);
  assert.match(page, /生态市场/);
  assert.match(page, /项目已安装/);
  assert.match(page, /API 与 SDK/);
  assert.match(page, /发布者中心/);
  assert.match(page, /data-testid="v4-ecosystem-page"/);
  assert.match(api, /\/api\/ecosystem\/marketplace/);
  assert.match(api, /\/service-accounts/);
});

test("V4 public API uses project-scoped service accounts, scopes and idempotency", () => {
  const service = readProject("backend-go/internal/service/ecosystem.go");
  const repo = readProject("backend-go/internal/repository/ecosystem.go");
  const router = readProject("backend-go/internal/router/ecosystem.go");
  assert.match(service, /am_sk_/);
  assert.match(service, /serviceAccountSecretHash/);
  assert.match(service, /subtle\.ConstantTimeCompare/);
  assert.match(service, /tasks:read/);
  assert.match(service, /tasks:write/);
  assert.match(service, /ReserveAPIIdempotencyRecord/);
  assert.match(service, /ProjectIDByConversation/);
  assert.match(repo, /secret_hash/);
  assert.match(repo, /IN_PROGRESS/);
  assert.match(repo, /COMPLETED/);
  assert.match(router, /\/openapi\/v1/);
  assert.match(router, /\/tasks\/run/);
});

test("V4 marketplace validation is typed, permission-aware and blocks private remote endpoints", () => {
  const service = readProject("backend-go/internal/service/ecosystem.go");
  assert.match(service, /AGENT.*MCP.*PLUGIN/s);
  assert.match(service, /network:outbound/);
  assert.match(service, /mcp:connect/);
  assert.match(service, /IsPrivate/);
  assert.match(service, /localhost/);
  assert.match(service, /https/);
  assert.match(service, /packageRequiresAdmin/);
  assert.match(service, /safeAuditMetadata/);
});

test("V4 install lifecycle materializes Agent and MCP resources and supports disable/uninstall", () => {
  const service = readProject("backend-go/internal/service/ecosystem.go");
  const schema = readProject("backend-go/internal/db/v4_platform_ecosystem_schema.go");
  assert.match(service, /materializePackage/);
  assert.match(service, /removeMaterializedPackage/);
  assert.match(service, /SetInstallationEnabled/);
  assert.match(service, /DeleteInstallation/);
  assert.match(schema, /project_package_installations/);
  assert.match(schema, /api_service_accounts/);
  assert.match(schema, /ecosystem_package_versions/);
});

test("V4 frontend never models or renders persisted secret hashes", () => {
  const types = read("src/types.ts");
  const page = read("src/features/ecosystem/Ecosystem.tsx");
  assert.doesNotMatch(types, /secretHash/);
  assert.doesNotMatch(types, /secret_hash/);
  assert.doesNotMatch(page, /secretHash/);
  assert.match(page, /API Key 只展示这一次/);
  assert.match(page, /v4-api-key-reveal/);
});

test("V4 dedicated browser and SDK acceptance runners are wired", () => {
  const pkg = JSON.parse(read("package.json"));
  const e2e = read("e2e/v4-platform-ecosystem-browser-e2e.mjs");
  assert.equal(pkg.scripts["test:e2e:v4"], "node e2e/v4-platform-ecosystem-browser-e2e.mjs");
  assert.match(e2e, /V4 Platform Ecosystem Browser E2E: PASS/);
  assert.match(e2e, /生态中心/);
  const py = readProject("sdk/python/agentmesh/client.py");
  const ts = readProject("sdk/typescript/src/index.ts");
  const pyTest = readProject("sdk/python/tests/test_client_integration.py");
  const tsTest = readProject("sdk/typescript/tests/client.integration.test.mjs");
  const openapi = readProject("docs/v4/openapi.yaml");
  const acceptance = readProject("scripts/TEST_V4_PLATFORM_ECOSYSTEM.ps1");
  assert.match(py, /Idempotency-Key/);
  assert.match(ts, /Idempotency-Key/);
  assert.match(pyTest, /Authorization/);
  assert.match(tsTest, /idempotency-key/);
  assert.match(openapi, /\/openapi\/v1\/tasks\/run/);
  assert.match(openapi, /ServiceAccountBearer/);
  assert.match(acceptance, /V4 Platform Ecosystem targeted acceptance: PASS/);
});
