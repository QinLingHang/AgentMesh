import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import net from "node:net";
import path from "node:path";
import process from "node:process";

const loopback = "127.0.0.1";
const webRoot = path.resolve(import.meta.dirname, "..");
const projectRoot = path.resolve(webRoot, "..");
const backendRoot = path.join(projectRoot, "backend-go");
const memberDisplayName = "P12 Browser Member";

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function withTimeout(promise, timeoutMs, label) {
  let timer;
  try {
    return await Promise.race([
      Promise.resolve(promise),
      new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error(`${label} timed out after ${timeoutMs}ms`)), timeoutMs);
      }),
    ]);
  } finally {
    if (timer) clearTimeout(timer);
  }
}

function envelopeData(raw) {
  return raw?.data ?? raw;
}

async function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", reject);
    server.listen(0, loopback, () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : 0;
      server.close(() => resolve(port));
    });
  });
}

function browserCandidates() {
  const env = process.env.P12_BROWSER_BIN || process.env.P11_BROWSER_BIN;
  const candidates = env ? [env] : [];
  if (process.platform === "win32") {
    candidates.push(
      "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
      "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
      "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
      "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
    );
  } else {
    candidates.push("/usr/bin/chromium", "/usr/bin/google-chrome", "/usr/bin/chromium-browser");
  }
  return candidates;
}

function resolveBrowser() {
  for (const candidate of browserCandidates()) {
    if (candidate && fs.existsSync(candidate)) return candidate;
  }
  throw new Error("No Chrome/Chromium/Edge binary found. Set P12_BROWSER_BIN explicitly.");
}

async function waitForUrl(url, timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs;
  let lastError;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url, { redirect: "manual" });
      if (response.status < 500) return response;
    } catch (error) {
      lastError = error;
    }
    await sleep(150);
  }
  throw lastError ?? new Error(`Timed out waiting for ${url}`);
}

async function waitForJson(url, timeoutMs = 10000) {
  const response = await waitForUrl(url, timeoutMs);
  return await response.json();
}

function waitForChildExit(child, timeoutMs = 5000) {
  if (!child || child.exitCode !== null || child.signalCode !== null) return Promise.resolve(true);
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

async function stopChild(child) {
  if (!child) return;

  try {
    if (child.exitCode === null && child.signalCode === null) {
      if (process.platform === "win32" && child.pid) {
        const killer = spawn("taskkill", ["/PID", String(child.pid), "/T", "/F"], {
          stdio: "ignore",
          windowsHide: true,
        });
        await withTimeout(
          new Promise((resolve) => {
            killer.once("error", resolve);
            killer.once("exit", resolve);
            killer.once("close", resolve);
          }),
          5000,
          `taskkill ${child.pid}`,
        ).catch(() => {
          try { killer.kill(); } catch {}
        });
        await waitForChildExit(child, 5000);
      } else {
        try { child.kill("SIGTERM"); } catch {}
        if (!(await waitForChildExit(child, 2500))) {
          try { child.kill("SIGKILL"); } catch {}
          await waitForChildExit(child, 2500);
        }
      }
    }
  } finally {
    child.stdout?.destroy();
    child.stderr?.destroy();
    child.stdin?.destroy();
    child.unref?.();
  }
}

async function closeBrowser(child, cdp) {
  if (cdp) {
    try {
      await withTimeout(cdp.send("Browser.close"), 1500, "Browser.close");
    } catch {}
    try { cdp.close(); } catch {}
  }
  await withTimeout(stopChild(child), 8000, "browser process cleanup");
}

async function cleanupProfile(profile) {
  for (let i = 0; i < 25; i += 1) {
    try {
      fs.rmSync(profile, { recursive: true, force: true });
      return;
    } catch (error) {
      if (!error || !["EBUSY", "EPERM", "ENOTEMPTY"].includes(error.code) || i === 24) throw error;
      await sleep(160);
    }
  }
}

function spawnCollected(command, args, options = {}, timeoutMs = 30000) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { ...options, stdio: ["ignore", "pipe", "pipe"] });
    let stdout = "";
    let stderr = "";
    let settled = false;
    const finish = (callback) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      callback();
    };
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      void stopChild(child).finally(() => {
        reject(new Error(`${command} ${args.join(" ")} timed out after ${timeoutMs}ms\nSTDOUT:\n${stdout}\nSTDERR:\n${stderr}`));
      });
    }, timeoutMs);
    child.stdout?.on("data", (chunk) => { stdout += String(chunk); });
    child.stderr?.on("data", (chunk) => { stderr += String(chunk); });
    child.once("error", (error) => finish(() => reject(error)));
    child.once("exit", (code) => finish(() => {
      if (code === 0) resolve({ stdout, stderr });
      else reject(new Error(`${command} ${args.join(" ")} exited ${code}\nSTDOUT:\n${stdout}\nSTDERR:\n${stderr}`));
    }));
  });
}

async function runFixture(action, args = []) {
  const { stdout } = await spawnCollected("go", ["run", "./cmd/p12-e2e-fixture", action, ...args], {
    cwd: backendRoot,
    env: process.env,
  });
  const lines = stdout.trim().split(/\r?\n/).filter(Boolean);
  return JSON.parse(lines.at(-1));
}

class CDP {
  constructor(url) {
    this.id = 0;
    this.pending = new Map();
    this.handlers = new Map();
    this.ws = new WebSocket(url);
  }
  async connect() {
    await new Promise((resolve, reject) => {
      this.ws.addEventListener("open", resolve, { once: true });
      this.ws.addEventListener("error", reject, { once: true });
    });
    this.ws.addEventListener("message", (event) => {
      const message = JSON.parse(String(event.data));
      if (message.id && this.pending.has(message.id)) {
        const { resolve, reject } = this.pending.get(message.id);
        this.pending.delete(message.id);
        if (message.error) reject(new Error(message.error.message));
        else resolve(message.result);
        return;
      }
      for (const handler of this.handlers.get(message.method) ?? []) handler(message.params ?? {});
    });
  }
  on(method, handler) {
    const list = this.handlers.get(method) ?? [];
    list.push(handler);
    this.handlers.set(method, list);
  }
  send(method, params = {}) {
    const id = ++this.id;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }
  async evaluate(expression) {
    const result = await this.send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.text ?? "Runtime.evaluate failed");
    return result.result.value;
  }
  close() { this.ws.close(); }
}

async function waitForPageTarget(debugPort, timeoutMs = 15000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const targets = await waitForJson(`http://${loopback}:${debugPort}/json/list`, 1000);
      const page = targets.find((target) => target.type === "page" && target.webSocketDebuggerUrl);
      if (page) return page;
    } catch {}
    await sleep(100);
  }
  throw new Error("Timed out waiting for browser page target");
}

async function waitFor(cdp, expression, label, timeoutMs = 15000) {
  const deadline = Date.now() + timeoutMs;
  let lastError;
  while (Date.now() < deadline) {
    try {
      if (await cdp.evaluate(`Boolean(${expression})`)) return;
    } catch (error) {
      lastError = error;
    }
    await sleep(120);
  }
  let body = "";
  try { body = await cdp.evaluate("document.body?.innerText ?? ''"); } catch {}
  throw new Error(`Timed out waiting for ${label}. ${lastError?.message ?? ""}\nBody:\n${body}`);
}

function q(value) {
  return JSON.stringify(value);
}

function clickTextExpression(text, selector = "button") {
  return `(() => { const el=[...document.querySelectorAll(${q(selector)})].find((node)=>node.textContent?.trim().includes(${q(text)})); if(!el)return false; el.click(); return true; })()`;
}

function setValueExpression(selector, value, index = 0) {
  return `(() => { const el=document.querySelectorAll(${q(selector)})[${index}]; if(!el)return false; const proto=el instanceof HTMLTextAreaElement?HTMLTextAreaElement.prototype:el instanceof HTMLSelectElement?HTMLSelectElement.prototype:HTMLInputElement.prototype; const setter=Object.getOwnPropertyDescriptor(proto,'value')?.set; if(setter)setter.call(el,${q(value)}); else el.value=${q(value)}; el.dispatchEvent(new Event('input',{bubbles:true})); el.dispatchEvent(new Event('change',{bubbles:true})); return true; })()`;
}

async function clickText(cdp, text, selector = "button") {
  assert.equal(await cdp.evaluate(clickTextExpression(text, selector)), true, `missing clickable text: ${text}`);
}

async function clickSelector(cdp, selector, label = selector) {
  assert.equal(
    await cdp.evaluate(`(() => { const el=document.querySelector(${q(selector)}); if(!el)return false; el.click(); return true; })()`),
    true,
    `missing clickable selector: ${label}`,
  );
}

async function setValue(cdp, selector, value, index = 0) {
  assert.equal(await cdp.evaluate(setValueExpression(selector, value, index)), true, `missing input: ${selector}[${index}]`);
}

async function selectValue(cdp, selector, value) {
  await setValue(cdp, selector, value, 0);
}

async function waitForVerificationCode(getLogs, email, scene, timeoutMs = 10000) {
  const deadline = Date.now() + timeoutMs;
  const escapedEmail = email.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const pattern = new RegExp(`\\[DEV EMAIL\\] to=${escapedEmail} scene=${scene} code=(\\d{6})`);
  while (Date.now() < deadline) {
    const match = getLogs().match(pattern);
    if (match) return match[1];
    await sleep(100);
  }
  throw new Error(`Timed out waiting for ${scene} verification code for ${email}\nServer log:\n${getLogs()}`);
}

async function registerOwner(cdp, owner) {
  await waitFor(cdp, `document.querySelector('[data-testid="auth-login-form"]')`, "registration auth shell");
  await clickSelector(cdp, '[data-testid="auth-open-register"]', "open register");
  await waitFor(cdp, `document.querySelector('[data-testid="auth-register-form"]')`, "register view");
  await setValue(cdp, `[data-testid="auth-email"]`, owner.email);
  await clickSelector(cdp, '[data-testid="auth-send-code-register"]', "send register verification code");
  const code = await waitForVerificationCode(owner.logs, owner.email, "register");
  await setValue(cdp, `[data-testid="auth-code-register"]`, code);
  await setValue(cdp, `input[autocomplete="name"]`, owner.displayName);
  await setValue(cdp, `input[autocomplete="new-password"]`, owner.password, 0);
  await setValue(cdp, `input[autocomplete="new-password"]`, owner.password, 1);
  await clickSelector(cdp, '[data-testid="auth-submit"]', "register submit");
  await waitFor(cdp, `document.querySelector('.app-shell') && document.querySelector('.user-card strong')?.textContent?.includes(${q(owner.displayName)})`, "registered authenticated shell", 20000);
}

async function passwordLogin(cdp, owner) {
  await waitFor(cdp, `document.querySelector('[data-testid="auth-login-form"]')`, "login shell");
  const passwordTab = await cdp.evaluate(`Boolean(document.querySelector('[data-testid="auth-password-login-tab"]'))`);
  if (passwordTab) await clickSelector(cdp, '[data-testid="auth-password-login-tab"]', "password login tab");
  await setValue(cdp, `[data-testid="auth-email"]`, owner.email);
  await setValue(cdp, `input[autocomplete="current-password"]`, owner.password);
  await clickSelector(cdp, '[data-testid="auth-submit"]', "login submit");
  await waitFor(cdp, `document.querySelector('.app-shell') && document.querySelector('.user-card strong')?.textContent?.includes(${q(owner.displayName)})`, "password login", 20000);
}

async function hardReloadAndAssertSession(cdp, refreshRequests, hostname, label) {
  const before = refreshRequests.filter((url) => new URL(url).hostname === hostname).length;
  await cdp.send("Page.reload", { ignoreCache: true });
  await sleep(300);
  await waitFor(cdp, `document.querySelector('.app-shell') && !document.querySelector('[data-testid="auth-page"]')`, `${label} authenticated reload`, 20000);
  const after = refreshRequests.filter((url) => new URL(url).hostname === hostname).length;
  assert.ok(after > before, `${label} reload must call same-origin /api/auth/refresh`);
}

async function logoutAndAssert(cdp) {
  await clickSelector(cdp, '[data-testid="auth-logout"]', "logout button");
  await waitFor(cdp, `document.querySelector('[data-testid="auth-page"]') && !document.querySelector('.app-shell')`, "logout auth shell");
  await cdp.send("Page.reload", { ignoreCache: true });
  await sleep(250);
  await waitFor(cdp, `document.querySelector('[data-testid="auth-page"]') && !document.querySelector('.app-shell')`, "logout persistence after reload");
}

async function createProjectThroughBrowser(cdp, name) {
  let opened = await cdp.evaluate(`(() => { const el=document.querySelector('[data-testid="project-create-open"]') ?? document.querySelector('[data-testid="project-create-empty"]'); if(!el)return false; el.click(); return true; })()`);
  assert.equal(opened, true, "project create entry missing");
  await waitFor(cdp, `document.querySelector('.workspace-management-dialog')`, "project creation dialog");
  await setValue(cdp, `[data-testid="project-name-input"]`, name);
  await clickSelector(cdp, '[data-testid="project-editor-submit"]', "project create submit");
  await waitFor(cdp, `[...document.querySelectorAll('.session-project-list *')].some((el)=>el.textContent?.includes(${q(name)}))`, "created project");
}

async function organizationFlow(cdp, fixture, names) {
  await clickSelector(cdp, '[data-testid="nav-governance"]', "governance nav");
  await waitFor(cdp, `document.querySelector('[data-testid="organization-section"]')`, "Organization / Workspace section");

  await setValue(cdp, `[data-testid="organization-name-input"]`, names.organization);
  await clickSelector(cdp, '[data-testid="organization-create-submit"]', "create organization");
  await waitFor(cdp, `[...document.querySelectorAll('[data-testid="organization-chip"]')].some((el)=>el.textContent?.includes(${q(names.organization)}))`, "created organization");

  await cdp.evaluate(`(() => { const el=[...document.querySelectorAll('[data-testid="organization-chip"]')].find((node)=>node.textContent?.includes(${q(names.organization)})); if(!el) return false; el.click(); return true; })()`);
  await waitFor(cdp, `document.querySelector('[data-testid="project-team-confirmed"]')?.textContent?.includes(${q(names.organization)})`, "project team confirmed");

  await setValue(cdp, `[data-testid="project-member-email"]`, fixture.memberEmail);
  await selectValue(cdp, `[data-testid="project-member-role"]`, "DEVELOPER");
  await clickSelector(cdp, '[data-testid="project-member-submit"]', "invite project member once");
  await waitFor(cdp, `document.querySelector('[data-testid="project-member-email"]')?.value === ''`, "project member submit");

  await cdp.send("Page.reload", { ignoreCache: true });
  await sleep(300);
  await waitFor(cdp, `document.querySelector('.app-shell')`, "session after organization reload", 20000);
  await clickSelector(cdp, '[data-testid="nav-governance"]', "governance nav after reload");
  await waitFor(cdp, `[...document.querySelectorAll('[data-testid="organization-chip"]')].some((el)=>el.textContent?.includes(${q(names.organization)}))`, "organization persistence after browser reload", 20000);

  await runFixture("verify", [
    "--database", fixture.database,
    "--organization", names.organization,
    "--project", names.project,
    "--member", fixture.memberEmail,
  ]);
}

async function run() {
  if (!process.env.P2_TEST_MYSQL_DSN) {
    throw new Error("P2_TEST_MYSQL_DSN is required; P12 final browser acceptance must use an isolated real MySQL database");
  }
  const viteEntry = path.join(webRoot, "node_modules", "vite", "bin", "vite.js");
  if (!fs.existsSync(viteEntry)) throw new Error(`Vite entry not found: ${viteEntry}`);

  const fixture = await runFixture("prepare");
  const backendPort = await freePort();
  const frontPort = await freePort();
  const debugPort = await freePort();
  const profile = fs.mkdtempSync(path.join(process.cwd(), ".p12-session-browser-"));
  const knowledgeRoot = fs.mkdtempSync(path.join(process.cwd(), ".p12-session-knowledge-"));
  const stamp = Date.now();
  const owner = {
    email: `p12-browser-owner-${stamp}@example.test`,
    password: "P12OwnerPass!123",
    displayName: "P12 Session QA",
    logs: () => serverLog,
  };
  const names = {
    project: `P12 Browser Project ${stamp}`,
    organization: `P12 Browser Org ${stamp}`,
  };

  let serverLog = "";
  let goServer;
  let vite;
  let browserChild;
  let cdp;
  let cleanupError;
  let primaryError;
  try {
    goServer = spawn("go", ["run", "./cmd/server"], {
      cwd: backendRoot,
      env: {
        ...process.env,
        BUSINESS_PORT: String(backendPort),
        MYSQL_HOST: fixture.host,
        MYSQL_PORT: fixture.port,
        MYSQL_DATABASE: fixture.database,
        MYSQL_USER: fixture.user,
        MYSQL_PASSWORD: fixture.password,
        REDIS_ADDR: process.env.P12_E2E_REDIS_ADDR || "127.0.0.1:6382",
        REDIS_PASSWORD: process.env.P12_E2E_REDIS_PASSWORD || "",
        REDIS_DB: process.env.P12_E2E_REDIS_DB || "14",
        JWT_SECRET: "p12-browser-jwt-secret-0123456789abcdef",
        JWT_ISSUER: "agentmesh-p12-browser",
        JWT_ACCESS_TTL_MINUTES: "30",
        JWT_REFRESH_TTL_DAYS: "3",
        AUTH_REFRESH_COOKIE_NAME: "refresh_token",
        AUTH_COOKIE_SECURE: "false",
        RUNTIME_BASE_URL: "http://127.0.0.1:1",
        RUNTIME_INTERNAL_TOKEN: "p12-browser-runtime-token-1234",
        RUNTIME_TIMEOUT_SECONDS: "2",
        MCP_DEMO_ENDPOINT: "http://127.0.0.1:1/mcp",
        ALLOWED_ORIGINS: `http://127.0.0.1:${frontPort},http://localhost:${frontPort}`,
        TASK_RATE_LIMIT_PER_MINUTE: "1000",
        DURABLE_RUNTIME_ENABLED: "false",
        GOVERNANCE_MASTER_KEY: "p12-browser-governance-key-0123456789",
        VERIFICATION_PEPPER: "p12-browser-verification-pepper-123",
        VERIFICATION_COOLDOWN_SECONDS: "1",
        EMAIL_PROVIDER: "console",
        KNOWLEDGE_STORAGE_ROOT: knowledgeRoot,
      },
      stdio: ["ignore", "pipe", "pipe"],
    });
    goServer.stdout?.on("data", (chunk) => { serverLog += String(chunk); });
    goServer.stderr?.on("data", (chunk) => { serverLog += String(chunk); });
    goServer.once("error", (error) => { serverLog += `\n[spawn error] ${error.stack ?? error}\n`; });
    await waitForUrl(`http://${loopback}:${backendPort}/health`, 45000);

    vite = spawn(process.execPath, [viteEntry, "--host", "0.0.0.0", "--port", String(frontPort)], {
      cwd: webRoot,
      env: { ...process.env, VITE_DEV_PROXY_TARGET: `http://${loopback}:${backendPort}` },
      stdio: ["ignore", "pipe", "pipe"],
    });
    await waitForUrl(`http://${loopback}:${frontPort}`, 30000);

    const browser = resolveBrowser();
    browserChild = spawn(browser, [
      "--headless=new",
      "--window-size=1440,1000",
      "--disable-gpu",
      "--no-sandbox",
      "--disable-dev-shm-usage",
      "--remote-allow-origins=*",
      `--remote-debugging-port=${debugPort}`,
      `--user-data-dir=${profile}`,
      "about:blank",
    ], { stdio: "ignore" });

    const page = await waitForPageTarget(debugPort);
    cdp = new CDP(page.webSocketDebuggerUrl);
    await cdp.connect();
    await cdp.send("Runtime.enable");
    await cdp.send("Page.enable");
    await cdp.send("Network.enable");
    await cdp.send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });

    const refreshRequests = [];
    cdp.on("Network.requestWillBeSent", ({ request }) => {
      if (request?.method === "POST" && request.url.includes("/api/auth/refresh")) refreshRequests.push(request.url);
    });

    const ipUrl = `http://127.0.0.1:${frontPort}`;
    await cdp.send("Page.navigate", { url: ipUrl });
    await registerOwner(cdp, owner);
    await hardReloadAndAssertSession(cdp, refreshRequests, "127.0.0.1", "127.0.0.1");
    await createProjectThroughBrowser(cdp, names.project);
    await organizationFlow(cdp, fixture, names);
    await logoutAndAssert(cdp);
    await passwordLogin(cdp, owner);

    const localhostUrl = `http://localhost:${frontPort}`;
    await cdp.send("Page.navigate", { url: localhostUrl });
    await waitFor(cdp, `document.querySelector('[data-testid="auth-login-form"]')`, "localhost login shell", 20000);
    await passwordLogin(cdp, owner);
    await hardReloadAndAssertSession(cdp, refreshRequests, "localhost", "localhost");
    await logoutAndAssert(cdp);
    await passwordLogin(cdp, owner);

    assert.ok(refreshRequests.some((url) => new URL(url).hostname === "127.0.0.1"), "127.0.0.1 refresh request not observed");
    assert.ok(refreshRequests.some((url) => new URL(url).hostname === "localhost"), "localhost refresh request not observed");

    console.log("P12 Real Go/MySQL Session + Organization Browser E2E: PASS");
  } catch (error) {
    primaryError = error;
  } finally {
    try { await withTimeout(closeBrowser(browserChild, cdp), 10000, "P12 browser cleanup"); } catch (error) { cleanupError ??= error; }
    for (const [label, child] of [["Vite", vite], ["Go server", goServer]]) {
      try { await withTimeout(stopChild(child), 10000, `P12 ${label} cleanup`); } catch (error) { cleanupError ??= error; }
    }
    try { await withTimeout(cleanupProfile(profile), 6000, "P12 browser profile cleanup"); } catch (error) { cleanupError ??= error; }
    try { fs.rmSync(knowledgeRoot, { recursive: true, force: true }); } catch (error) { cleanupError ??= error; }
    try { await withTimeout(runFixture("cleanup", ["--database", fixture.database]), 35000, "P12 fixture cleanup"); } catch (error) { cleanupError ??= error; }
  }

  if (primaryError) {
    if (serverLog) console.error(`P12 real Go server log:\n${serverLog}`);
    if (cleanupError) console.error(`P12 cleanup warning: ${cleanupError.stack ?? cleanupError}`);
    throw primaryError;
  }
  if (cleanupError) throw cleanupError;
}

try {
  await run();
  process.exit(0);
} catch (error) {
  console.error(error?.stack ?? error);
  process.exit(1);
}
