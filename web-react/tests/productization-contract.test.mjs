import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const root = path.resolve(import.meta.dirname, "..");
const read = (relative) => fs.readFileSync(path.join(root, relative), "utf8");

test("Browser E2E/Release Browser browser API defaults to same-origin in development and production", () => {
  const api = read("src/api.ts");
  const vite = read("vite.config.ts");
  assert.match(api, /const DEFAULT_BASE = ""/);
  assert.match(api, /VITE_API_BASE_URL \?\?/);
  assert.match(vite, /proxy:[\s\S]*?"\/api"[\s\S]*?VITE_DEV_PROXY_TARGET[\s\S]*?http:\/\/127\.0\.0\.1:8086/);
});

test("Browser E2E shell lazy-loads secondary product modules and Run Details", () => {
  const app = read("src/App.tsx");
  const workspace = read("src/features/workspace/Workspace.tsx");
  for (const moduleName of ["Agents", "KnowledgeCenter", "Extensions", "Tasks", "Governance"]) {
    assert.match(app, new RegExp(`const ${moduleName} = lazy`));
  }
  assert.match(app, /<Suspense/);
  assert.match(app, /AppErrorBoundary/);
  assert.match(workspace, /const RunDetails = lazy/);
  assert.match(workspace, /正在加载 Run Details/);
});

test("Browser E2E surfaces actionable network permission and quota errors instead of raw Error strings", () => {
  const api = read("src/api.ts");
  const workspace = read("src/features/workspace/Workspace.tsx");
  const governance = read("src/features/governance/Governance.tsx");
  assert.match(api, /你没有权限执行此操作/);
  assert.match(api, /当前项目额度或请求频率已达到限制/);
  assert.match(api, /无法连接 AgentMesh 服务/);
  assert.match(workspace, /friendlyApiError/);
  assert.match(governance, /friendlyApiError/);
});

test("Browser E2E includes a zero-dependency real-browser E2E harness", () => {
  const e2e = read("e2e/browser-e2e.mjs");
  assert.match(e2e, /remote-debugging-port/);
  assert.match(e2e, /WebSocket/);
  assert.match(e2e, /Browser E2E: PASS/);
  assert.match(e2e, /--window-size=1440,1000/);
  assert.match(e2e, /Emulation\.setDeviceMetricsOverride/);
  assert.match(e2e, /document\.querySelector\('\.app-shell'\)/);
  assert.match(e2e, /document\.querySelector\('\.user-card strong'\)/);
  assert.match(e2e, /assertPage\(cdp, "治理与安全", "治理与安全"\)/);
  assert.match(e2e, /document\.querySelectorAll\(\'main h2\'\)/);
  assert.match(e2e, /Team collaboration section/);
  assert.match(e2e, /assertPage\(cdp, "工作台", "工作台", "\.workspace-breadcrumb span"\)/);
  assert.match(e2e, /clickButtonExpression\("高级安全与模型设置"\)/);
  assert.match(e2e, /clickButtonExpression\("审计记录"\)/);
  assert.match(e2e, /audit-card \.audit-actor/);
  assert.match(e2e, /friendly 429 error/);
});


test("Release Browser local direct-API fallback allows both localhost and 127.0.0.1 browser origins", () => {
  const backendConfig = read("../backend-go/internal/config/config.go");
  const backendEnv = read("../backend-go/.env.example");
  assert.match(backendConfig, /http:\/\/localhost:5173,http:\/\/127\.0\.0\.1:5173/);
  assert.match(backendEnv, /ALLOWED_ORIGINS=http:\/\/localhost:5173,http:\/\/127\.0\.0\.1:5173/);
});


test("Release Browser session restore harness uses real Go/MySQL, real Vite, both loopback hostnames, and Organization persistence", () => {
  const e2e = read("e2e/dev-session-restore.mjs");
  const fixture = read("../backend-go/cmd/browser-e2e-fixture/main.go");
  const pkg = JSON.parse(read("package.json"));
  assert.doesNotMatch(e2e, /createBackend\(/);
  assert.doesNotMatch(e2e, /npm\.cmd/);
  assert.match(e2e, /node_modules["\s,]+"vite"["\s,]+"bin"["\s,]+"vite\.js/);
  assert.match(e2e, /spawn\("go", \["run", "\.\/cmd\/server"\]/);
  assert.match(e2e, /QA_TEST_MYSQL_DSN/);
  assert.match(e2e, /http:\/\/127\.0\.0\.1:/);
  assert.match(e2e, /http:\/\/localhost:/);
  assert.match(e2e, /Network\.requestWillBeSent/);
  assert.match(e2e, /\/api\/auth\/refresh/);
  assert.match(e2e, /Page\.reload/);
  assert.match(e2e, /auth-open-register/);
  assert.match(e2e, /auth-send-code-register/);
  assert.match(e2e, /auth-logout/);
  assert.match(e2e, /auth-submit/);
  assert.match(e2e, /organization-create-submit/);
  assert.match(e2e, /project-member-submit/);
  assert.match(e2e, /project-team-confirmed/);
  assert.match(e2e, /runFixture\("verify"/);
  assert.match(e2e, /withTimeout/);
  assert.match(e2e, /taskkill/);
  assert.match(e2e, /process\.exit\(0\)/);
  assert.match(fixture, /organization_members/);
  assert.match(fixture, /organization_projects/);
  assert.equal(pkg.scripts["test:e2e:session"], "node e2e/dev-session-restore.mjs");
});


test("Release Browser final browser flow is localization/encoding independent via stable ASCII test ids", () => {
  const e2e = read("e2e/dev-session-restore.mjs");
  const auth = read("src/features/auth/Auth.tsx");
  const code = read("src/features/auth/VerificationCodeField.tsx");
  const app = read("src/App.tsx");
  const rail = read("src/features/workspace/SessionRail.tsx");
  const governance = read("src/features/governance/Governance.tsx");

  assert.doesNotMatch(e2e, /[\u4e00-\u9fff]/);
  for (const marker of [
    "auth-open-register",
    "auth-submit",
    "auth-email",
    "auth-password-login-tab",
  ]) assert.match(auth, new RegExp(marker));
  assert.match(code, /auth-send-code-\$\{scene\}/);
  assert.match(code, /auth-code-\$\{scene\}/);
  assert.match(app, /nav-\$\{item\.id\}/);
  assert.match(app, /auth-logout/);
  assert.match(rail, /project-create-open/);
  assert.match(rail, /project-name-input/);
  assert.match(rail, /project-editor-submit/);
  assert.match(governance, /organization-create-submit/);
  assert.match(governance, /project-member-submit/);
  assert.match(governance, /project-team-confirmed/);
});


test("Release Browser session restore uses stable auth-page selector", () => {
  const auth = read("src/features/auth/Auth.tsx");
  const e2e = read("e2e/dev-session-restore.mjs");
  assert.match(auth, /data-testid="auth-page"/);
  assert.match(e2e, /data-testid=\"auth-page\"/);
  assert.doesNotMatch(e2e, /\.auth-shell/);
});
