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
const state = { governanceRateLimited: false };

function envelope(data) {
  return JSON.stringify({ code: 0, message: "ok", data });
}

function errorEnvelope(status, message) {
  return JSON.stringify({ code: status === 429 ? 42901 : status, message });
}

const now = "2026-09-06T09:00:00Z";
const project = {
  id: 1,
  userId: 7,
  name: "P11 Browser QA",
  description: "Browser E2E project",
  conversationIds: [],
  createdAt: now,
  updatedAt: now,
};

const routes = new Map([
  ["GET /api/me", { id: 7, email: "p11@example.com", displayName: "P11 QA", status: "ACTIVE" }],
  ["GET /api/conversations", []],
  ["GET /api/projects", [project]],
  ["GET /api/agents", []],
  ["GET /api/runtime/plugins", []],
  ["GET /api/tasks", []],
  ["GET /api/tools", []],
  ["GET /api/mcp-servers", []],
  ["GET /api/knowledge/bases", []],
  ["GET /api/knowledge/files", []],
  ["GET /api/runtime/reliability", {
    enabled: true,
    queueDepth: 0,
    leased: 0,
    accepted: 0,
    failed: 0,
    canceled: 0,
    workers: 1,
    availableWorkers: 1,
    drainingWorkers: 0,
    circuitOpenWorkers: 0,
    oldestQueuedMs: 0,
  }],
  ["GET /api/organizations", [{ id: 11, ownerId: 7, name: "P11 QA Org", createdAt: now, updatedAt: now }]],
]);

const governance = {
  role: "OWNER",
  members: [
    { projectId: 1, userId: 7, email: "p11@example.com", displayName: "P11 QA", role: "OWNER", createdAt: now, updatedAt: now },
  ],
  quota: {
    projectId: 1,
    requestsPerMinute: 60,
    concurrentTasks: 4,
    monthlyTokenLimit: 1000000,
    monthlyCostLimit: 100,
    dailyToolActionLimit: 500,
  },
  usage: {
    projectId: 1,
    monthKey: "2026-09",
    requestCount: 12,
    tokenCount: 4200,
    estimatedCost: 1.23,
    toolActionCount: 8,
    concurrentTasks: 0,
  },
  secrets: [{ id: 21, projectId: 1, name: "OPENAI_API_KEY", kind: "MODEL_API_KEY", maskedHint: "••••7890", createdBy: 7, createdAt: now, updatedAt: now }],
  modelProvider: {
    projectId: 1,
    provider: "openai-compatible",
    baseUrl: "https://api.openai.com/v1",
    modelName: "gpt-4.1-mini",
    secretId: 21,
    enabled: true,
    createdAt: now,
    updatedAt: now,
  },
  audit: [{ id: 31, projectId: 1, actorUserId: 7, action: "quota.update", resourceType: "project_quota", resourceId: "1", result: "SUCCESS", createdAt: now }],
};

function contentType(filename) {
  if (filename.endsWith(".html")) return "text/html; charset=utf-8";
  if (filename.endsWith(".js")) return "text/javascript; charset=utf-8";
  if (filename.endsWith(".css")) return "text/css; charset=utf-8";
  if (filename.endsWith(".svg")) return "image/svg+xml";
  return "application/octet-stream";
}

function createServer() {
  return http.createServer((req, res) => {
    const requestUrl = new URL(req.url ?? "/", `http://${host}`);
    const key = `${req.method ?? "GET"} ${requestUrl.pathname}`;

    if (requestUrl.pathname === "/__p11__/rate-limit") {
      state.governanceRateLimited = true;
      res.writeHead(204).end();
      return;
    }

    if (key === "GET /api/projects/1/governance") {
      if (state.governanceRateLimited) {
        state.governanceRateLimited = false;
        res.writeHead(429, { "content-type": "application/json" });
        res.end(errorEnvelope(429, "quota exceeded"));
        return;
      }
      res.writeHead(200, { "content-type": "application/json" });
      res.end(envelope(governance));
      return;
    }

    if (routes.has(key)) {
      res.writeHead(200, { "content-type": "application/json" });
      res.end(envelope(routes.get(key)));
      return;
    }

    if (requestUrl.pathname.startsWith("/api/")) {
      res.writeHead(404, { "content-type": "application/json" });
      res.end(errorEnvelope(404, `mock route missing: ${key}`));
      return;
    }

    let filePath = path.join(dist, requestUrl.pathname === "/" ? "index.html" : requestUrl.pathname);
    if (!path.resolve(filePath).startsWith(path.resolve(dist))) {
      res.writeHead(403).end();
      return;
    }
    if (!fs.existsSync(filePath) || fs.statSync(filePath).isDirectory()) {
      filePath = path.join(dist, "index.html");
    }
    if (!fs.existsSync(filePath)) {
      res.writeHead(500).end("dist missing; run npm run build first");
      return;
    }
    res.writeHead(200, { "content-type": contentType(filePath), "cache-control": "no-store" });
    fs.createReadStream(filePath).pipe(res);
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
  const env = process.env.P11_BROWSER_BIN ? [process.env.P11_BROWSER_BIN] : [];
  if (process.platform === "win32") {
    return [
      ...env,
      "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
      "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
      "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
      "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
    ];
  }
  return [...env, "/usr/bin/chromium", "/usr/bin/google-chrome", "/usr/bin/chromium-browser"];
}

function resolveBrowser() {
  for (const candidate of browserCandidates()) {
    if (candidate && fs.existsSync(candidate)) return candidate;
  }
  throw new Error("No Chrome/Chromium/Edge binary found. Set P11_BROWSER_BIN explicitly.");
}


function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function waitForChildExit(child, timeoutMs = 5000) {
  if (child.exitCode !== null || child.signalCode !== null) return Promise.resolve(true);
  return new Promise((resolve) => {
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      child.off("exit", onExit);
      child.off("close", onExit);
      resolve(value);
    };
    const onExit = () => finish(true);
    const timer = setTimeout(() => finish(false), timeoutMs);
    child.once("exit", onExit);
    child.once("close", onExit);
  });
}

async function forceKillBrowserTree(child) {
  if (child.exitCode !== null || child.signalCode !== null) return;

  try {
    child.kill();
  } catch {
    // The browser may already be exiting.
  }
  if (await waitForChildExit(child, 3000)) return;

  if (process.platform === "win32" && child.pid) {
    await new Promise((resolve) => {
      const killer = spawn("taskkill", ["/PID", String(child.pid), "/T", "/F"], { stdio: "ignore" });
      killer.once("error", () => resolve());
      killer.once("exit", () => resolve());
    });
    await waitForChildExit(child, 3000);
    return;
  }

  try {
    child.kill("SIGKILL");
  } catch {
    // Best effort only.
  }
  await waitForChildExit(child, 3000);
}

async function closeBrowser(child, cdp) {
  if (cdp) {
    try {
      await cdp.send("Browser.close");
    } catch {
      // Fall back to terminating the spawned browser process.
    }
    try {
      cdp.close();
    } catch {
      // Best effort only.
    }
  }

  if (!(await waitForChildExit(child, 5000))) {
    await forceKillBrowserTree(child);
  }
}

async function closeServer(server) {
  if (!server.listening) return;
  await new Promise((resolve) => server.close(() => resolve()));
}

async function removeProfileWithRetry(profile, attempts = 20, delayMs = 150) {
  let lastError;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      fs.rmSync(profile, { recursive: true, force: true, maxRetries: 0 });
      return;
    } catch (error) {
      lastError = error;
      if (!error || !["EBUSY", "EPERM", "ENOTEMPTY"].includes(error.code) || attempt === attempts) {
        throw error;
      }
      await sleep(delayMs);
    }
  }
  if (lastError) throw lastError;
}

async function waitForJson(url, timeoutMs = 10000) {
  const deadline = Date.now() + timeoutMs;
  let lastError;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok) return await response.json();
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw lastError ?? new Error(`Timed out waiting for ${url}`);
}


async function waitForPageTarget(debugPort, timeoutMs = 10000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const targets = await waitForJson(`http://${host}:${debugPort}/json/list`, 1000);
      const page = targets.find((target) => target.type === "page" && target.webSocketDebuggerUrl);
      if (page) return page;
    } catch {
      // Browser may still be starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error("Timed out waiting for a browser page target");
}

class CDP {
  constructor(url) {
    this.id = 0;
    this.pending = new Map();
    this.ws = new WebSocket(url);
  }

  async connect() {
    await new Promise((resolve, reject) => {
      this.ws.addEventListener("open", resolve, { once: true });
      this.ws.addEventListener("error", reject, { once: true });
    });
    this.ws.addEventListener("message", (event) => {
      const message = JSON.parse(String(event.data));
      if (!message.id || !this.pending.has(message.id)) return;
      const { resolve, reject } = this.pending.get(message.id);
      this.pending.delete(message.id);
      if (message.error) reject(new Error(message.error.message));
      else resolve(message.result);
    });
  }

  send(method, params = {}) {
    const id = ++this.id;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }

  async evaluate(expression) {
    const result = await this.send("Runtime.evaluate", {
      expression,
      awaitPromise: true,
      returnByValue: true,
    });
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.text ?? "Runtime.evaluate failed");
    return result.result.value;
  }

  close() {
    this.ws.close();
  }
}

async function waitFor(cdp, predicateExpression, label, timeoutMs = 10000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await cdp.evaluate(`Boolean(${predicateExpression})`)) return;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  const body = await cdp.evaluate("document.body.innerText");
  throw new Error(`Timed out waiting for ${label}. Body was:\n${body}`);
}

function clickButtonExpression(label) {
  return `(() => { const target = [...document.querySelectorAll('button')].find((node) => node.textContent?.trim().includes(${JSON.stringify(label)})); if (!target) return false; target.click(); return true; })()`;
}

async function assertPage(cdp, navLabel, heading, selector = "main h1") {
  assert.equal(await cdp.evaluate(clickButtonExpression(navLabel)), true, `nav button ${navLabel} should exist`);
  await waitFor(
    cdp,
    `document.querySelector(${JSON.stringify(selector)})?.textContent?.includes(${JSON.stringify(heading)})`,
    heading,
  );
}

async function run() {
  assert.ok(fs.existsSync(path.join(dist, "index.html")), "dist/index.html missing; run npm run build first");
  const serverPort = await freePort();
  const debugPort = await freePort();
  const server = createServer();
  await new Promise((resolve) => server.listen(serverPort, host, resolve));
  const appUrl = `http://${host}:${serverPort}`;
  const profile = fs.mkdtempSync(path.join(process.cwd(), ".p11-browser-"));
  const browser = resolveBrowser();
  const child = spawn(browser, [
    "--headless=new",
    "--window-size=1440,1000",
    "--disable-gpu",
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--remote-allow-origins=*",
    `--remote-debugging-port=${debugPort}`,
    `--user-data-dir=${profile}`,
    appUrl,
  ], { stdio: "ignore" });

  let cdp;
  let primaryError;
  let cleanupError;
  let lazyAssetCount = 0;
  try {
    const page = await waitForPageTarget(debugPort);
    assert.ok(page.webSocketDebuggerUrl, "browser page target unavailable");
    cdp = new CDP(page.webSocketDebuggerUrl);
    await cdp.connect();
    await cdp.send("Runtime.enable");
    await cdp.send("Page.enable");
    await cdp.send("Emulation.setDeviceMetricsOverride", {
      width: 1440,
      height: 1000,
      deviceScaleFactor: 1,
      mobile: false,
      screenWidth: 1440,
      screenHeight: 1000,
    });

    await waitFor(
      cdp,
      `document.querySelector('.app-shell') && document.querySelector('.user-card strong')?.textContent?.trim() === "P11 QA" && !document.querySelector('.auth-shell')`,
      "authenticated shell",
    );
    await waitFor(cdp, `document.body.innerText.includes("工作台")`, "workspace navigation");

    const initialJsResources = await cdp.evaluate(
      `[...performance.getEntriesByType('resource')].filter((entry) => entry.name.includes('/assets/') && entry.name.endsWith('.js')).length`,
    );

    await assertPage(cdp, "智能体", "智能体");
    const lazyJsResources = await cdp.evaluate(
      `[...performance.getEntriesByType('resource')].filter((entry) => entry.name.includes('/assets/') && entry.name.endsWith('.js')).length`,
    );
    assert.ok(lazyJsResources > initialJsResources, "opening a secondary module should load a lazy JS chunk");
    await assertPage(cdp, "知识库", "知识库");
    await assertPage(cdp, "能力中心", "让 AgentMesh 做得更多");
    await assertPage(cdp, "任务记录", "任务");
    await assertPage(cdp, "治理与安全", "治理与安全");
    await waitFor(
      cdp,
      `[...document.querySelectorAll('main h2')].some((node) => node.textContent?.includes("团队协作"))`,
      "Team collaboration section",
    );

    assert.equal(
      await cdp.evaluate(clickButtonExpression("高级安全与模型设置")),
      true,
      "advanced governance toggle should exist",
    );
    await waitFor(cdp, `document.body.innerText.includes("••••7890")`, "masked secret hint");
    assert.equal(await cdp.evaluate(`document.body.innerText.includes("plaintext-secret")`), false);

    assert.equal(
      await cdp.evaluate(clickButtonExpression("审计记录")),
      true,
      "audit toggle should exist",
    );
    await waitFor(
      cdp,
      `document.querySelector('.audit-card .audit-actor')?.textContent?.includes("用户 #7")`,
      "audit actor",
    );

    await fetch(`${appUrl}/__p11__/rate-limit`);
    await assertPage(cdp, "工作台", "工作台", ".workspace-breadcrumb span");
    await assertPage(cdp, "治理与安全", "治理与安全");
    await waitFor(cdp, `document.body.innerText.includes("当前项目额度或请求频率已达到限制")`, "friendly 429 error");

    const jsAssets = fs.readdirSync(path.join(dist, "assets")).filter((name) => name.endsWith(".js"));
    assert.ok(jsAssets.length >= 4, `expected code splitting, got ${jsAssets.length} JS asset(s)`);
    lazyAssetCount = jsAssets.length;
  } catch (error) {
    primaryError = error;
  } finally {
    const cleanupFailures = [];
    try {
      await closeBrowser(child, cdp);
    } catch (error) {
      cleanupFailures.push(new Error(`browser shutdown failed: ${error.message}`, { cause: error }));
    }
    try {
      await closeServer(server);
    } catch (error) {
      cleanupFailures.push(new Error(`test server shutdown failed: ${error.message}`, { cause: error }));
    }
    try {
      await removeProfileWithRetry(profile);
    } catch (error) {
      cleanupFailures.push(new Error(`browser profile cleanup failed: ${error.message}`, { cause: error }));
    }

    if (cleanupFailures.length > 0) {
      cleanupError = cleanupFailures.length === 1
        ? cleanupFailures[0]
        : new AggregateError(cleanupFailures, "P11 browser cleanup failed");
    }
  }

  if (primaryError) {
    if (cleanupError) console.error("P11 Browser E2E cleanup warning:", cleanupError);
    throw primaryError;
  }
  if (cleanupError) throw cleanupError;

  console.log("P11 Browser E2E: PASS");
  console.log(`Browser: ${browser}`);
  console.log(`Lazy JS assets: ${lazyAssetCount}`);
}

run().catch((error) => {
  console.error("P11 Browser E2E: FAIL");
  console.error(error);
  process.exitCode = 1;
});
