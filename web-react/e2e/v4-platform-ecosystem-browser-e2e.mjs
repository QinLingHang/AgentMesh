import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import net from "node:net";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..");
const dist = path.join(root, "dist");
const host = "127.0.0.1";
const now = "2026-09-07T12:00:00Z";

const user = { id: 7, email: "v4-browser@example.test", displayName: "V4 Browser QA", status: "ACTIVE" };
const project = { id: 1, userId: 7, name: "生态验收项目", description: "V4 deterministic browser fixture", conversationIds: [], createdAt: now, updatedAt: now };
const pkg = { id: 41, ownerUserId: 7, slug: "research-agent", name: "Research Agent", kind: "AGENT", summary: "可复用研究智能体", description: "fixture", visibility: "PUBLIC", status: "PUBLISHED", latestVersion: "1.0.0", installCount: 3, createdAt: now, updatedAt: now };
const rawAPIKey = "am_sk_browser_fixture_<ONE_TIME_ONLY>";
const state = { installations: [], accounts: [] };

function envelope(data, message = "ok") { return JSON.stringify({ code: 0, message, data }); }
function errorEnvelope(status, message) { return JSON.stringify({ code: status, message, data: null }); }
function contentType(filename) {
  if (filename.endsWith(".html")) return "text/html; charset=utf-8";
  if (filename.endsWith(".js")) return "text/javascript; charset=utf-8";
  if (filename.endsWith(".css")) return "text/css; charset=utf-8";
  if (filename.endsWith(".svg")) return "image/svg+xml";
  return "application/octet-stream";
}
async function readJson(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  if (chunks.length === 0) return {};
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

function createServer() {
  return http.createServer(async (req, res) => {
    try {
      const url = new URL(req.url ?? "/", `http://${host}`);
      const key = `${req.method ?? "GET"} ${url.pathname}`;
      const fixed = new Map([
        ["GET /api/me", user],
        ["GET /api/conversations", []],
        ["GET /api/projects", [project]],
        ["GET /api/agents", []],
        ["GET /api/runtime/plugins", []],
        ["GET /api/tools", []],
        ["GET /api/mcp-servers", []],
        ["GET /api/knowledge/bases", []],
        ["GET /api/organizations", []],
        ["GET /api/tasks", []],
        ["GET /api/runtime/reliability", { enabled: true, queueDepth: 0, workers: 2, availableWorkers: 2, nodes: 2, availableNodes: 2, totalCapacity: 8, activeExecutions: 0, utilizationPercent: 0, dispatcherLeader: true, dispatcherEpoch: 9 }],
        ["GET /api/ecosystem/overview", { publishedPackages: 3, agentPackages: 1, mcpPackages: 1, pluginPackages: 1, totalInstalls: 12 }],
        ["GET /api/ecosystem/marketplace", [pkg]],
      ]);
      if (fixed.has(key)) {
        res.writeHead(200, { "content-type": "application/json" });
        res.end(envelope(fixed.get(key)));
        return;
      }
      if (key === "GET /api/runtime/topology") {
        res.writeHead(200, { "content-type": "application/json" });
        res.end(envelope({ reliability: fixed.get("GET /api/runtime/reliability"), nodes: [], workers: [] }));
        return;
      }
      if (key === "GET /api/projects/1/ecosystem/installations") {
        res.writeHead(200, { "content-type": "application/json" });
        res.end(envelope(state.installations));
        return;
      }
      if (key === "GET /api/projects/1/service-accounts") {
        res.writeHead(200, { "content-type": "application/json" });
        res.end(envelope(state.accounts));
        return;
      }
      if (key === "POST /api/projects/1/ecosystem/installations") {
        await readJson(req);
        const installation = { id: 71, projectId: 1, packageId: 41, versionId: 101, packageSlug: pkg.slug, packageName: pkg.name, kind: "AGENT", version: "1.0.0", enabled: true, config: {}, resourceType: "AGENT", resourceId: 901, installedBy: 7, createdAt: now, updatedAt: now };
        state.installations = [installation];
        pkg.installCount += 1;
        res.writeHead(200, { "content-type": "application/json" });
        res.end(envelope(installation));
        return;
      }
      if (key === "POST /api/projects/1/service-accounts") {
        const body = await readJson(req);
        const account = { id: 81, projectId: 1, name: body.name || "生产 API", keyPrefix: "am_sk_browser", scopes: body.scopes || ["tasks:read"], status: "ACTIVE", createdBy: 7, requestCount: 0, errorCount: 0, createdAt: now, updatedAt: now };
        state.accounts = [account];
        res.writeHead(201, { "content-type": "application/json" });
        res.end(envelope({ serviceAccount: account, apiKey: rawAPIKey }, "API Key 仅本次返回，请立即安全保存"));
        return;
      }
      if (key === "POST /api/ecosystem/packages/validate") {
        await readJson(req);
        res.writeHead(200, { "content-type": "application/json" });
        res.end(envelope({ valid: true, kind: "AGENT", schemaVersion: "agentmesh.dev/v1", permissions: [], checksum: "A".repeat(64) }));
        return;
      }
      if (key === "POST /api/ecosystem/packages") {
        await readJson(req);
        res.writeHead(201, { "content-type": "application/json" });
        res.end(envelope({ package: { ...pkg, id: 42, slug: "my-agent-template", name: "我的 Agent 模板" }, versions: [] }));
        return;
      }
      if (key.startsWith("GET /api/ecosystem/packages/") && key.endsWith("/export")) {
        res.writeHead(200, { "content-type": "application/json" });
        res.end(envelope({ formatVersion: "agentmesh.bundle/v1", package: pkg, version: { id: 101, packageId: 41, version: "1.0.0", manifest: { schemaVersion: "agentmesh.dev/v1", kind: "AGENT", permissions: [], agent: { name: "Research Agent", endpoint: "https://agent.example.com/a2a", protocol: "a2a", capabilities: ["research"] } }, checksum: "A".repeat(64), status: "VALIDATED", createdBy: 7, createdAt: now } }));
        return;
      }
      if (url.pathname.startsWith("/api/")) {
        res.writeHead(404, { "content-type": "application/json" });
        res.end(errorEnvelope(404, `mock route missing: ${key}`));
        return;
      }
      let filePath = path.join(dist, url.pathname === "/" ? "index.html" : url.pathname);
      if (!path.resolve(filePath).startsWith(path.resolve(dist))) { res.writeHead(403).end(); return; }
      if (!fs.existsSync(filePath) || fs.statSync(filePath).isDirectory()) filePath = path.join(dist, "index.html");
      if (!fs.existsSync(filePath)) { res.writeHead(500).end("dist missing; run npm run build first"); return; }
      res.writeHead(200, { "content-type": contentType(filePath), "cache-control": "no-store" });
      fs.createReadStream(filePath).pipe(res);
    } catch (error) {
      res.writeHead(500, { "content-type": "text/plain; charset=utf-8" });
      res.end(error.stack ?? String(error));
    }
  });
}

async function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", reject);
    server.listen(0, host, () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : 0;
      server.close(() => resolve(port));
    });
  });
}
function browserCandidates() {
  const configured = process.env.V4_BROWSER_BIN || process.env.BROWSER_E2E_BIN;
  const env = configured ? [configured] : [];
  if (process.platform === "win32") return [...env, "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe", "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe", "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe", "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe"];
  return [...env, "/usr/bin/chromium", "/usr/bin/google-chrome", "/usr/bin/chromium-browser"];
}
function resolveBrowser() {
  for (const candidate of browserCandidates()) if (candidate && fs.existsSync(candidate)) return candidate;
  throw new Error("No Chrome/Chromium/Edge binary found. Set V4_BROWSER_BIN explicitly.");
}
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
function waitForChildExit(child, timeoutMs = 5000) {
  if (child.exitCode !== null || child.signalCode !== null) return Promise.resolve(true);
  return new Promise((resolve) => {
    let settled = false;
    const finish = (value) => { if (settled) return; settled = true; clearTimeout(timer); child.off("exit", onExit); child.off("close", onExit); resolve(value); };
    const onExit = () => finish(true);
    const timer = setTimeout(() => finish(false), timeoutMs);
    child.once("exit", onExit); child.once("close", onExit);
  });
}
async function forceKillBrowserTree(child) {
  if (child.exitCode !== null || child.signalCode !== null) return;
  try { child.kill(); } catch {}
  if (await waitForChildExit(child, 3000)) return;
  if (process.platform === "win32" && child.pid) {
    await new Promise((resolve) => { const killer = spawn("taskkill", ["/PID", String(child.pid), "/T", "/F"], { stdio: "ignore" }); killer.once("error", resolve); killer.once("exit", resolve); });
    await waitForChildExit(child, 3000); return;
  }
  try { child.kill("SIGKILL"); } catch {}
  await waitForChildExit(child, 3000);
}
async function closeBrowser(child, cdp) {
  if (cdp) { try { await cdp.send("Browser.close"); } catch {} try { cdp.close(); } catch {} }
  if (!(await waitForChildExit(child, 5000))) await forceKillBrowserTree(child);
}
async function closeServer(server) { if (server.listening) await new Promise((resolve) => server.close(resolve)); }
async function removeProfileWithRetry(profile, attempts = 20, delayMs = 150) {
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try { fs.rmSync(profile, { recursive: true, force: true, maxRetries: 0 }); return; }
    catch (error) { if (!error || !["EBUSY", "EPERM", "ENOTEMPTY"].includes(error.code) || attempt === attempts) throw error; await sleep(delayMs); }
  }
}
async function waitForJson(url, timeoutMs = 10000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) { try { const response = await fetch(url); if (response.ok) return await response.json(); } catch {} await sleep(100); }
  throw new Error(`Timed out waiting for ${url}`);
}
async function waitForPageTarget(debugPort, timeoutMs = 10000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) { try { const targets = await waitForJson(`http://${host}:${debugPort}/json/list`, 1000); const page = targets.find((target) => target.type === "page" && target.webSocketDebuggerUrl); if (page) return page; } catch {} await sleep(100); }
  throw new Error("Timed out waiting for browser page target");
}
class CDP {
  constructor(url) { this.id = 0; this.pending = new Map(); this.ws = new WebSocket(url); }
  async connect() { await new Promise((resolve, reject) => { this.ws.addEventListener("open", resolve, { once: true }); this.ws.addEventListener("error", reject, { once: true }); }); this.ws.addEventListener("message", (event) => { const message = JSON.parse(String(event.data)); if (!message.id || !this.pending.has(message.id)) return; const { resolve, reject } = this.pending.get(message.id); this.pending.delete(message.id); if (message.error) reject(new Error(message.error.message)); else resolve(message.result); }); }
  send(method, params = {}) { const id = ++this.id; return new Promise((resolve, reject) => { this.pending.set(id, { resolve, reject }); this.ws.send(JSON.stringify({ id, method, params })); }); }
  async evaluate(expression) { const result = await this.send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true }); if (result.exceptionDetails) throw new Error(result.exceptionDetails.text ?? "Runtime.evaluate failed"); return result.result.value; }
  close() { this.ws.close(); }
}
async function waitFor(cdp, predicateExpression, label, timeoutMs = 12000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) { if (await cdp.evaluate(`Boolean(${predicateExpression})`)) return; await sleep(100); }
  const body = await cdp.evaluate("document.body.innerText");
  throw new Error(`Timed out waiting for ${label}. Body was:\n${body}`);
}
async function clickText(cdp, label) {
  const expression = `(() => { const nodes=[...document.querySelectorAll('button')]; const target=nodes.find((node)=>node.textContent?.trim().includes(${JSON.stringify(label)})); if(!target)return false; target.click(); return true; })()`;
  assert.equal(await cdp.evaluate(expression), true, `button ${label} should exist`);
}

async function run() {
  assert.ok(fs.existsSync(path.join(dist, "index.html")), "dist/index.html missing; run npm run build first");
  const serverPort = await freePort(); const debugPort = await freePort();
  const server = createServer(); await new Promise((resolve) => server.listen(serverPort, host, resolve));
  const profile = fs.mkdtempSync(path.join(process.cwd(), ".v4-browser-"));
  const child = spawn(resolveBrowser(), ["--headless=new", "--window-size=1440,1000", "--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage", "--remote-allow-origins=*", `--remote-debugging-port=${debugPort}`, `--user-data-dir=${profile}`, `http://${host}:${serverPort}`], { stdio: "ignore" });
  let cdp; let primaryError; let cleanupError;
  try {
    const page = await waitForPageTarget(debugPort); cdp = new CDP(page.webSocketDebuggerUrl); await cdp.connect(); await cdp.send("Runtime.enable"); await cdp.send("Page.enable");
    await waitFor(cdp, `document.querySelector('.app-shell') && document.querySelector('.user-card strong')?.textContent?.trim() === "V4 Browser QA"`, "authenticated shell");
    assert.equal(await cdp.evaluate(`(() => { const n=document.querySelector('[data-testid="nav-ecosystem"]'); if(!n)return false; n.click(); return true; })()`), true);
    await waitFor(cdp, `document.querySelector('[data-testid="v4-ecosystem-page"]') && document.querySelector('main h1')?.textContent?.includes("生态中心")`, "ecosystem center");
    await waitFor(cdp, `document.querySelector('[data-testid="marketplace-package-research-agent"]') && document.body.innerText.includes("Research Agent")`, "marketplace package");
    assert.equal(await cdp.evaluate(`document.body.innerText.includes("secret_hash") || document.body.innerText.includes("internal-test-token")`), false, "secret/internal token must not leak");

    await clickText(cdp, "安装到项目");
    await waitFor(cdp, `document.body.innerText.includes("已安装到")`, "package install notice");
    await clickText(cdp, "项目已安装");
    await waitFor(cdp, `document.querySelector('[data-testid="v4-installations"]') && document.body.innerText.includes("AGENT #901")`, "materialized installation");

    await clickText(cdp, "API 与 SDK");
    await waitFor(cdp, `document.querySelector('[data-testid="v4-public-api"]') && document.body.innerText.includes("项目级机器身份")`, "public API panel");
    await clickText(cdp, "创建 API Key");
    await waitFor(cdp, `document.querySelector('[data-testid="v4-api-key-reveal"]') && document.body.innerText.includes(${JSON.stringify(rawAPIKey)})`, "one-time API key reveal");
    await waitFor(cdp, `document.body.innerText.includes("tasks:read") && document.body.innerText.includes("tasks:write")`, "service account scopes");

    await clickText(cdp, "发布者中心");
    await waitFor(cdp, `document.querySelector('[data-testid="v4-publisher"]')`, "publisher center");
    await clickText(cdp, "校验清单");
    await waitFor(cdp, `document.body.innerText.includes("Manifest 校验通过") && document.body.innerText.includes("已校验")`, "manifest validation");

    console.log("V4 Platform Ecosystem Browser E2E: PASS");
  } catch (error) { primaryError = error; }
  finally {
    try { await closeBrowser(child, cdp); } catch (error) { cleanupError ??= error; }
    try { await closeServer(server); } catch (error) { cleanupError ??= error; }
    try { await removeProfileWithRetry(profile); } catch (error) { cleanupError ??= error; }
  }
  if (primaryError) { if (cleanupError) console.error(`V4 browser cleanup warning: ${cleanupError.stack ?? cleanupError}`); throw primaryError; }
  if (cleanupError) throw cleanupError;
}

await run();
