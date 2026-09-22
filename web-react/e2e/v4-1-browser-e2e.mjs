import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import net from "node:net";
import path from "node:path";
import process from "node:process";
import { groundedFixtureKnowledgeReply, probeFixtureKnowledgeEvidence } from "./knowledge-fixture-evidence.mjs";
import { cdpElementExists, reportFailurePreservingPrimary } from "./qa-cdp-diagnostics.mjs";
import { projectCitationReadyExpression, projectCitationDiagnosticExpression } from "./project-citation-dom.mjs";

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

async function runFixture(action, args = [], extraEnv = {}) {
  const { stdout } = await spawnCollected("go", ["run", "./cmd/p12-e2e-fixture", action, ...args], {
    cwd: backendRoot,
    env: { ...process.env, ...extraEnv },
  });
  const lines = stdout.trim().split(/\r?\n/).filter(Boolean);
  return JSON.parse(lines.at(-1));
}

async function runP20MemoryFixture(action, args = []) {
  const { stdout } = await spawnCollected("go", ["run", "./cmd/p20-memory-e2e-fixture", action, ...args], {
    cwd: backendRoot,
    env: process.env,
  }, 45000);
  const lines = stdout.trim().split(/\r?\n/).filter(Boolean);
  return JSON.parse(lines.at(-1));
}

async function inspectRuntimeMemory(runtimePython, runtimeRoot, redisUrl, memoryPrefix) {
  const script = [
    'import json, os',
    'import redis',
    'client = redis.Redis.from_url(os.environ["P20_REDIS_URL"], decode_responses=False)',
    'prefix = os.environ["P20_MEMORY_PREFIX"]',
    'items = []',
    'for key in client.scan_iter(match=(prefix + ":*").encode("utf-8")):',
    '    kind = client.type(key).decode("utf-8")',
    '    size = client.llen(key) if kind == "list" else 0',
    '    items.append({"key": key.decode("utf-8"), "type": kind, "listLength": int(size)})',
    'print(json.dumps({"items": items, "maxListLength": max([x["listLength"] for x in items] or [0])}))',
  ].join('\n');
  const { stdout } = await spawnCollected(runtimePython, ['-c', script], {
    cwd: runtimeRoot,
    env: { ...process.env, P20_REDIS_URL: redisUrl, P20_MEMORY_PREFIX: memoryPrefix },
  }, 15000);
  return JSON.parse(stdout.trim().split(/\r?\n/).filter(Boolean).at(-1));
}

function redisDatabaseFromUrl(rawUrl) {
  let parsed;
  try {
    parsed = new URL(rawUrl);
  } catch (error) {
    throw new Error(`Invalid V4.1 Runtime Redis URL: ${error?.message ?? error}`);
  }
  if (!['redis:', 'rediss:'].includes(parsed.protocol)) {
    throw new Error(`V4.1 Runtime Redis URL must use redis:// or rediss://, got ${parsed.protocol}`);
  }
  const rawDb = parsed.pathname.replace(/^\/+/, '') || '0';
  const db = Number(rawDb);
  if (!Number.isInteger(db) || db < 0) {
    throw new Error(`V4.1 Runtime Redis URL has invalid database index: ${rawDb}`);
  }
  return db;
}

async function cleanupRuntimeMemory(runtimePython, runtimeRoot, redisUrl, memoryPrefix) {
  const cleanupScript = [
    'import os',
    'import redis',
    'url = os.environ["V4_1_QA_RUNTIME_REDIS_URL"]',
    'prefix = os.environ["V4_1_QA_MEMORY_PREFIX"]',
    'client = redis.Redis.from_url(url, decode_responses=False)',
    'client.ping()',
    'keys = list(client.scan_iter(match=(prefix + ":*").encode("utf-8")))',
    'if keys:',
    '    client.delete(*keys)',
  ].join('\n');
  await spawnCollected(runtimePython, ['-c', cleanupScript], {
    cwd: runtimeRoot,
    env: {
      ...process.env,
      V4_1_QA_RUNTIME_REDIS_URL: redisUrl,
      V4_1_QA_MEMORY_PREFIX: memoryPrefix,
    },
  }, 15000);
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
  // Never dump the entire page on failure: the Workspace can contain private
  // Knowledge, tokens, prompts and results. Each critical gate emits a bounded,
  // purpose-built metadata diagnostic instead.
  throw new Error(`Timed out waiting for ${label}. ${lastError?.message ?? ""}`);
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

function redactQaDiagnostics(raw) {
  return String(raw ?? "")
    .replace(
      /(\[DEV EMAIL\][^\r\n]*\bcode=)\d{6}\b/g,
      "$1[REDACTED]",
    );
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
  throw new Error(
    `Timed out waiting for ${scene} verification code for ${email}\nServer log:\n${redactQaDiagnostics(getLogs())}`,
  );
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


function unwrap(raw) {
  if (raw && typeof raw === "object" && Object.prototype.hasOwnProperty.call(raw, "data")) return raw.data;
  return raw;
}

async function apiRequest(baseUrl, accessToken, method, route, body, headers = {}) {
  const init = {
    method,
    headers: {
      Authorization: `Bearer ${accessToken}`,
      ...headers,
    },
  };
  if (body !== undefined) init.body = body;
  const response = await fetch(`${baseUrl}${route}`, init);
  const text = await response.text();
  let payload = null;
  if (text) {
    try { payload = JSON.parse(text); } catch { payload = text; }
  }
  if (!response.ok || (payload && typeof payload === "object" && Number(payload.code ?? 0) !== 0)) {
    throw new Error(`${method} ${route} failed: HTTP ${response.status} ${text}`);
  }
  return unwrap(payload);
}

async function internalMemoryRequest(baseUrl, internalToken, method, route, body) {
  const headers = {};
  if (internalToken) headers["X-Internal-Token"] = internalToken;
  if (body !== undefined) headers["content-type"] = "application/json";
  const response = await fetch(`${baseUrl}${route}`, {
    method,
    headers,
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  });
  const text = await response.text();
  let payload = null;
  if (text) {
    try { payload = JSON.parse(text); } catch { payload = text; }
  }
  return { response, payload, data: unwrap(payload) };
}

async function waitForConversationCapsules(baseUrl, internalToken, userId, conversationId, timeoutMs = 25000) {
  const route = `/internal/v1/users/${userId}/conversations/${conversationId}/memory-capsules?limit=20`;
  const deadline = Date.now() + timeoutMs;
  let last = null;
  while (Date.now() < deadline) {
    const result = await internalMemoryRequest(baseUrl, internalToken, "GET", route);
    if (result.response.ok && Array.isArray(result.data) && result.data.length > 0) return result.data;
    last = result;
    await sleep(150);
  }
  throw new Error(`conversation capsule was not persisted in time: ${JSON.stringify(last?.payload ?? null)}`);
}

async function loadAllConversationHistory(cdp, expectedAtLeast, timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs;
  for (let page = 0; page < 20 && Date.now() < deadline; page += 1) {
    const state = await cdp.evaluate(`(() => ({
      count: document.querySelectorAll('[data-testid="message-user"], [data-testid="message-assistant"]').length,
      hasMore: Boolean(document.querySelector('[data-testid="message-history-load-earlier"] button')),
    }))()`);
    if (!state.hasMore) {
      assert.ok(state.count >= expectedAtLeast, `expected at least ${expectedAtLeast} durable messages, got ${state.count}`);
      return state.count;
    }
    const before = state.count;
    assert.equal(
      await cdp.evaluate(`(() => { const button=document.querySelector('[data-testid="message-history-load-earlier"] button'); if(!button||button.disabled)return false; button.click(); return true; })()`),
      true,
      "load-earlier history button was not clickable",
    );
    await waitFor(
      cdp,
      `document.querySelectorAll('[data-testid="message-user"], [data-testid="message-assistant"]').length > ${before}`,
      `older history page after ${before} messages`,
      10000,
    );
  }
  throw new Error(`timed out loading complete durable conversation history (expected >= ${expectedAtLeast})`);
}


async function seedV41ModelService(fixture, email, modelPort) {
  const seeded = await runFixture(
    "seed-v4-1-model-service",
    [
      "--database", fixture.database,
      "--email", email,
      "--base-url", `http://${loopback}:${modelPort}/v1`,
      "--model-name", "v4-1-e2e",
    ],
    {
      V4_1_FIXTURE_GOVERNANCE_MASTER_KEY: "v4-1-browser-governance-key-0123456789",
      V4_1_FIXTURE_MODEL_API_KEY: "v4-1-e2e-model-key",
    },
  );
  assert.ok(Number(seeded?.serviceId) > 0, `V4.1 model fixture was not created for ${email}`);
  assert.equal(seeded?.enabled, true, `V4.1 model fixture is disabled for ${email}`);
  assert.equal(seeded?.autoRoute, true, `V4.1 model fixture is not auto-routable for ${email}`);
  assert.equal(seeded?.isDefault, true, `V4.1 model fixture is not default for ${email}`);
  return seeded;
}

async function ensureV41AgentBaseline(apiBase, accessToken, email) {
  // Full Runtime requests (Desktop / Knowledge / MCP / Skills) intentionally
  // execute through the user's configured Agent pool. Ordinary chat can use
  // InteractiveFastPath without an Agent, so a freshly registered QA user
  // must explicitly provision the same minimum Agent baseline that the
  // full-runtime product path requires. Keep this in the acceptance fixture;
  // do not weaken TaskService.loadRuntimeResources or auto-inject a hidden
  // production Agent merely to make the browser test pass.
  await apiRequest(apiBase, accessToken, "POST", "/api/agents/seed-demo");
  const agents = await apiRequest(apiBase, accessToken, "GET", "/api/agents");
  assert.ok(
    Array.isArray(agents) && agents.some((item) => item?.name === "GeneralAgent" && item?.protocol === "internal"),
    `Full Runtime Agent baseline is missing for ${email}`,
  );
}

// A rendered authenticated shell is not the same as a hydrated Workspace.
// The project rail is mounted by Workspace and may appear a moment after
// auth/model-service restoration. Wait for the actual visible, enabled control;
// never substitute an API project creation or a fixed sleep for this UI gate.
async function openCreateProjectWhenReady(cdp) {
  await waitFor(
    cdp,
    `(() => {
      const shell = document.querySelector('.app-shell.tab-workspace');
      const rail = shell?.querySelector('.session-rail');
      const button = rail?.querySelector('[data-testid="project-create-open"]');
      return Boolean(button && button.isConnected && !button.disabled && button.getClientRects().length > 0
        && getComputedStyle(rail).pointerEvents !== 'none'
        && getComputedStyle(rail).visibility !== 'hidden');
    })()`,
    "visible project-create button in hydrated workspace after model-service reload",
    20000,
  );
  await clickSelector(cdp, '[data-testid="project-create-open"]', "open create-project dialog");
}

// RAG V1.1 intentionally requires per-request user consent for personal Global
// Knowledge. Merely uploading a file does NOT turn USER_GLOBAL on. Configure
// the same real UI users see; never forge an API payload or widen Go policy.
async function setUserGlobalKnowledgeScope(cdp, enabled) {
  await waitFor(
    cdp,
    `(() => { const button=document.querySelector('[data-testid="run-settings-open"]');
      return Boolean(button && button.isConnected && !button.disabled && button.getClientRects().length > 0); })()`,
    "run settings button ready",
    20000,
  );
  await clickSelector(cdp, '[data-testid="run-settings-open"]', "open real run settings");
  await waitFor(
    cdp,
    `document.querySelector('.run-settings-drawer [data-testid="rag-scope-user-global"]')`,
    "global knowledge consent control ready",
    10000,
  );
  const scopeSelector = '.run-settings-drawer [data-testid="rag-scope-user-global"]';
  const previous = await cdp.evaluate(`document.querySelector(${q(scopeSelector)})?.checked`);
  assert.equal(typeof previous, "boolean", "global knowledge scope checkbox missing");
  if (previous !== enabled) await clickSelector(cdp, scopeSelector, "explicit global knowledge consent");
  await waitFor(cdp, `document.querySelector(${q(scopeSelector)})?.checked === ${enabled}`, "global knowledge consent state", 10000);
  await clickSelector(cdp, '[data-testid="run-settings-done"]', "save run settings through UI");
  await waitFor(cdp, `!document.querySelector('.run-settings-drawer')`, "run settings closed", 10000);
}

// Store only the policy fields required for the QA assertion, never tokens,
// full prompts, model credentials, attachment contents or raw response bodies.
function summarizeGlobalKnowledgeSubmission(request, targetPrompt) {
  if (!request?.url?.includes('/api/tasks/submit-stream') || !request.postData) return null;
  let payload;
  try { payload = JSON.parse(request.postData); } catch { return null; }
  if (payload?.task !== targetPrompt) return null;
  return {
    mode: payload.ragPolicy?.mode ?? null,
    scopes: payload.ragPolicy?.scopes ?? null,
    selectedKnowledgeBaseIds: payload.ragPolicy?.selectedKnowledgeBaseIds ?? null,
  };
}

function assertObservedGlobalKnowledgeSubmission(submissions, expectedEnabled, label) {
  const policy = submissions.at(-1);
  assert.ok(policy, `${label}: no browser submission policy captured; cannot claim effective authorization`);
  assert.equal(policy.mode, 'AUTO', `${label}: fixture must test natural AUTO knowledge discovery`);
  assert.ok(Array.isArray(policy.scopes), `${label}: request did not provide an explicit knowledge scope array`);
  assert.equal(policy.scopes.includes('USER_GLOBAL'), expectedEnabled, `${label}: browser request had unexpected Global Knowledge consent`);
  assert.deepEqual(policy.selectedKnowledgeBaseIds, [], `${label}: fixture must not force-select a knowledge base to fake discovery`);
}

async function verifyAndReloadV41ModelService(cdp, fixture, apiBase, accessToken, email, displayName, modelPort) {
  await seedV41ModelService(fixture, email, modelPort);
  const services = await apiRequest(apiBase, accessToken, "GET", "/api/me/model-services");
  assert.ok(
    Array.isArray(services) && services.some((item) => item?.enabled === true && item?.autoRoute === true && item?.isDefault === true && item?.modelName === "v4-1-e2e"),
    `Workspace model-service projection is missing the enabled V4.1 fixture for ${email}`,
  );
  await ensureV41AgentBaseline(apiBase, accessToken, email);
  await cdp.send("Page.reload", { ignoreCache: true });
  await waitFor(
    cdp,
    `document.querySelector('.app-shell') && document.querySelector('.user-card strong')?.textContent?.includes(${q(displayName)})`,
    `authenticated shell after V4.1 model fixture for ${email}`,
    20000,
  );
}

async function waitForKnowledgeReady(baseUrl, accessToken, knowledgeBaseId, fileId, timeoutMs = 120000) {
  const deadline = Date.now() + timeoutMs;
  let last = null;
  while (Date.now() < deadline) {
    const files = await apiRequest(baseUrl, accessToken, "GET", `/api/knowledge/bases/${knowledgeBaseId}/files`);
    last = (files ?? []).find((item) => Number(item.id) === Number(fileId));
    if (last?.status === "READY") return last;
    if (last?.status === "ERROR") throw new Error(`knowledge indexing failed: ${JSON.stringify(last)}`);
    await sleep(300);
  }
  throw new Error(`knowledge file ${fileId} did not reach READY: ${JSON.stringify(last)}`);
}

async function createKnowledgeFixture(baseUrl, accessToken, { name, scope, projectId = null, filename, content }) {
  const base = await apiRequest(
    baseUrl,
    accessToken,
    "POST",
    "/api/knowledge/bases",
    JSON.stringify({ name, description: "V4.1 browser acceptance fixture", scope, projectId }),
    { "Content-Type": "application/json" },
  );
  const form = new FormData();
  form.append("file", new Blob([content], { type: "text/plain;charset=utf-8" }), filename);
  const file = await apiRequest(baseUrl, accessToken, "POST", `/api/knowledge/bases/${base.id}/files`, form);
  const ready = await waitForKnowledgeReady(baseUrl, accessToken, base.id, file.id);
  assert.ok(Number(ready.textChunkCount) > 0,
    `knowledge file READY without indexed text: base=${base.id} file=${file.id} textChunks=${ready.textChunkCount}`);
  return { base, file, ready };
}

async function waitForAccessToken(getToken, timeoutMs = 10000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const token = getToken();
    if (token) return token;
    await sleep(100);
  }
  throw new Error("No Authorization bearer token observed after authentication");
}

async function currentConversationId(cdp) {
  const raw = await cdp.evaluate(`document.querySelector('[data-testid="workspace-conversation"]')?.dataset?.conversationId ?? ''`);
  const id = Number(raw);
  return Number.isFinite(id) && id > 0 ? id : 0;
}

async function waitForConversationHistoryReady(cdp, id, timeoutMs = 20000) {
  await waitFor(
    cdp,
    `document.querySelector('[data-testid="workspace-conversation"]')?.dataset?.conversationId === ${q(String(id))}`,
    `conversation ${id} active`,
    timeoutMs,
  );
  await waitFor(
    cdp,
    `document.querySelector('[data-testid="workspace-conversation"]')?.dataset?.messagesState !== "loading"`,
    `conversation ${id} history settled`,
    timeoutMs,
  );
  const historyState = await cdp.evaluate(`(() => {
    const root=document.querySelector('[data-testid="workspace-conversation"]');
    return {
      state: root?.dataset?.messagesState ?? '',
      error: document.querySelector('[data-testid="message-history-error"]')?.textContent ?? '',
    };
  })()`);
  assert.equal(
    historyState.state,
    "ready",
    `conversation ${id} history failed to load: ${historyState.error || historyState.state}`,
  );
}

async function createConversationThroughBrowser(cdp) {
  const before = await currentConversationId(cdp);
  await waitFor(
    cdp,
    `(() => { const button=document.querySelector('[data-testid="conversation-create"]'); return Boolean(button && !button.disabled); })()`,
    "new conversation button ready",
    15000,
  );
  await clickSelector(cdp, '[data-testid="conversation-create"]', "new conversation");
  await waitFor(
    cdp,
    `(() => { const id=Number(document.querySelector('[data-testid="workspace-conversation"]')?.dataset?.conversationId||0); return id>0 && id!==${before}; })()`,
    "new conversation selection",
    15000,
  );
  const id = await currentConversationId(cdp);
  await waitForConversationHistoryReady(cdp, id);
  return id;
}

async function openConversation(cdp, id) {
  const selector = `[data-testid="conversation-item-${id}"]`;
  await waitFor(
    cdp,
    `(() => { const item=document.querySelector(${q(selector)}); return Boolean(item && !item.disabled); })()`,
    `conversation ${id} rail item ready`,
    20000,
  );
  await clickSelector(cdp, selector, `conversation ${id}`);
  await waitForConversationHistoryReady(cdp, id);
}

async function assertConversationAtBottom(cdp, label, timeoutMs = 5000) {
  const deadline = Date.now() + timeoutMs;
  let last = null;
  while (Date.now() < deadline) {
    last = await cdp.evaluate(`(() => {
      const node=document.querySelector('[data-testid="workspace-message-scroll"]');
      if(!node)return null;
      return {
        scrollTop: node.scrollTop,
        scrollHeight: node.scrollHeight,
        clientHeight: node.clientHeight,
        distance: Math.max(0, node.scrollHeight - node.scrollTop - node.clientHeight),
      };
    })()`);
    if (last && last.distance <= 4) return last;
    await sleep(50);
  }
  throw new Error(`${label} did not land at the latest-message bottom: ${JSON.stringify(last)}`);
}

async function loadOneOlderPagePreservingViewport(cdp) {
  const before = await cdp.evaluate(`(() => {
    const node=document.querySelector('[data-testid="workspace-message-scroll"]');
    const button=document.querySelector('[data-testid="message-history-load-earlier"] button');
    if(!node||!button)return null;
    node.scrollTop=0;
    const anchor=document.querySelector('[data-testid="message-user"][data-message-id], [data-testid="message-assistant"][data-message-id]');
    const ids=[...document.querySelectorAll('[data-testid="message-user"], [data-testid="message-assistant"]')]
      .map((item)=>Number(item.getAttribute('data-message-id')||0));
    return {
      count: ids.length,
      ids,
      scrollTop: node.scrollTop,
      scrollHeight: node.scrollHeight,
      anchorId: anchor?.getAttribute('data-message-id') ?? null,
      anchorTop: anchor?.getBoundingClientRect().top ?? null,
    };
  })()`);
  assert.ok(before, "P20 older-history viewport fixture was unavailable");
  assert.ok(before.anchorId && Number.isFinite(before.anchorTop), "P20 visible message anchor was unavailable");

  assert.equal(
    await cdp.evaluate(`(() => { const button=document.querySelector('[data-testid="message-history-load-earlier"] button'); if(!button||button.disabled)return false; button.click(); return true; })()`),
    true,
    "P20 older-history button was not clickable",
  );

  await waitFor(
    cdp,
    `document.querySelectorAll('[data-testid="message-user"], [data-testid="message-assistant"]').length > ${before.count}`,
    "P20 first older-history page",
    10000,
  );

  await sleep(120);

  const after = await cdp.evaluate(`(() => {
    const node=document.querySelector('[data-testid="workspace-message-scroll"]');
    const anchor=document.querySelector('[data-message-id="${before.anchorId}"]');
    const ids=[...document.querySelectorAll('[data-testid="message-user"], [data-testid="message-assistant"]')]
      .map((item)=>Number(item.getAttribute('data-message-id')||0));
    return node ? {
      count: ids.length,
      ids,
      scrollTop: node.scrollTop,
      scrollHeight: node.scrollHeight,
      anchorTop: anchor?.getBoundingClientRect().top ?? null,
    } : null;
  })()`);

  assert.ok(after, "P20 older-history scroll container disappeared");

  const expectedTop =
    before.scrollTop +
    Math.max(
      0,
      after.scrollHeight -
        before.scrollHeight,
    );

  const scrollDisplacement =
    Math.abs(
      after.scrollTop -
        expectedTop,
    );

  const hasConcreteAnchor =
    Number.isFinite(
      after.anchorTop,
    );

  const anchorDisplacement =
    hasConcreteAnchor
      ? Math.abs(
          after.anchorTop -
            before.anchorTop,
        )
      : null;

  const diagnostics = {
    before: {
      ...before,
      firstIds: before.ids.slice(0, 5),
      lastIds: before.ids.slice(-5),
      ids: undefined,
    },
    after: {
      ...after,
      firstIds: after.ids.slice(0, 5),
      lastIds: after.ids.slice(-5),
      ids: undefined,
    },
    expectedTop,
    scrollDisplacement,
    anchorDisplacement,
    anchorMode:
      hasConcreteAnchor
        ? "concrete-element"
        : "height-fallback",
  };

  console.log(
    `[P20] older-history anchor ${JSON.stringify(diagnostics)}`,
  );

  if (hasConcreteAnchor) {
    assert.ok(
      anchorDisplacement <= 16,
      `loading older history displaced the visible message anchor: ${JSON.stringify(diagnostics)}`,
    );
    return;
  }

  // Height arithmetic is only authoritative when the concrete durable anchor
  // disappeared and production had to use its one-time missing-anchor fallback.
  assert.ok(
    scrollDisplacement <= 8,
    `loading older history fallback did not preserve the viewport: ${JSON.stringify(diagnostics)}`,
  );
}

async function composerValue(cdp) {
  return await cdp.evaluate(`document.querySelector('[data-testid="workspace-composer"]')?.value ?? ''`);
}

async function workspaceText(cdp) {
  return await cdp.evaluate(`document.querySelector('[data-testid="workspace-conversation"]')?.innerText ?? ''`);
}

async function durableMessageSnapshot(cdp) {
  return await cdp.evaluate(`(() => {
    const nodes=[...document.querySelectorAll('[data-testid="message-user"], [data-testid="message-assistant"]')];
    return {
      count: nodes.length,
      ids: nodes.map((node) => Number(node.getAttribute('data-message-id') || 0)),
      texts: nodes.map((node) => node.textContent || ''),
    };
  })()`);
}

function p20HistoryEvidence(label, snapshot, firstMarker, lastMarker) {
  const evidence = {
    count: snapshot.count,
    firstIds: snapshot.ids.slice(0, 5),
    lastIds: snapshot.ids.slice(-5),
    firstMarker: snapshot.texts.some((value) => value.includes(firstMarker)),
    lastMarker: snapshot.texts.some((value) => value.includes(lastMarker)),
  };
  console.log(`[P20] ${label} ${JSON.stringify(evidence)}`);
  return evidence;
}

async function sendPrompt(cdp, prompt, expectedText = "", timeoutMs = 90000) {
  const beforeSend = await cdp.evaluate(`(() => ({
    durableUserCount: document.querySelectorAll('[data-testid="message-user"]').length,
    durableAssistantCount: document.querySelectorAll('[data-testid="message-assistant"]').length,
  }))()`);

  await setValue(cdp, '[data-testid="workspace-composer"]', prompt);
  // A prior request can have persisted its assistant answer while Workspace is
  // still clearing its busy state. Only click when the real submit button is
  // enabled; never silently drop the next QA prompt or repeat the submission.
  await waitFor(
    cdp,
    `document.querySelector('[data-testid="workspace-submit"]')?.disabled === false`,
    "workspace submit ready for the next prompt",
    30000,
  );
  await clickSelector(cdp, '[data-testid="workspace-submit"]', "workspace submit");
  await waitFor(
    cdp,
    `[...document.querySelectorAll('[data-testid="message-user"], [data-testid="message-user-optimistic"]')].some((el)=>el.textContent?.includes(${q(prompt)}))`,
    `user prompt ${prompt}`,
    15000,
  );

  if (expectedText) {
    await waitFor(
      cdp,
      `[...document.querySelectorAll('[data-testid="message-assistant"], [data-testid="assistant-streaming-answer"]')].some((el)=>el.textContent?.includes(${q(expectedText)}))`,
      `assistant text ${expectedText}`,
      timeoutMs,
    );
    return;
  }

  // A conversation can already contain many assistant rows. Waiting for
  // "any assistant message" therefore returns immediately and can race the
  // authoritative same-conversation refresh. For no-specific-text calls,
  // wait until this submission itself is durable: the exact user prompt must
  // exist as a persisted user row and a new persisted assistant row must have
  // appeared beyond the pre-submit baseline.
  await waitFor(
    cdp,
    `(() => {
      const users=[...document.querySelectorAll('[data-testid="message-user"]')];
      const assistants=document.querySelectorAll('[data-testid="message-assistant"]');
      const promptPersisted=users.some((el)=>el.textContent?.includes(${q(prompt)}));
      return promptPersisted && assistants.length > ${beforeSend.durableAssistantCount};
    })()`,
    `durable assistant response for ${prompt}`,
    timeoutMs,
  );
}

async function openLatestRunDetails(cdp) {
  const buttons = await cdp.evaluate(`document.querySelectorAll('[data-testid="run-details-open"]').length`);
  assert.ok(buttons > 0, "run details opener missing");
  assert.equal(
    await cdp.evaluate(`(() => { const xs=[...document.querySelectorAll('[data-testid="run-details-open"]')]; const el=xs.at(-1); if(!el)return false; el.click(); return true; })()`),
    true,
  );
  await waitFor(cdp, `document.querySelector('[data-testid="run-details-drawer"]')`, "run details drawer");

  // Run Details is loaded through React.lazy. The drawer shell can mount before
  // the lazy tab content exists, so a fixed-instant click can race Suspense and
  // report a false missing-selector failure. Wait for the real interactive tab
  // surface instead of sleeping or warming the mount with a probe-only retry.
  await waitFor(
    cdp,
    `(() => { const drawer=document.querySelector('[data-testid="run-details-drawer"]'); return Boolean(drawer?.querySelector('[data-testid^="run-details-tab-"]')); })()`,
    "Run Details lazy tab surface",
    10000,
  );
}

async function closeRunDetails(cdp) {
  await clickSelector(cdp, '[data-testid="run-details-close"]', "close run details");
  await waitFor(cdp, `!document.querySelector('[data-testid="run-details-drawer"]')`, "run details closed", 5000);
}

function lastUserText(messages) {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (messages[index]?.role === "user") {
      const content = messages[index]?.content;
      if (typeof content === "string") return content;
      if (Array.isArray(content)) return content.map((item) => item?.text ?? "").join(" ");
    }
  }
  return "";
}

function flattenedMessageText(messages) {
  return messages.map((message) => typeof message?.content === "string" ? message.content : JSON.stringify(message?.content ?? "")).join("\n");
}

function promptSection(text, label) {
  const escaped = label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = String(text ?? "").match(
    new RegExp(`\\[${escaped}\\]\\s*\\n([\\s\\S]*?)(?=\\n\\[[^\\]]+\\]\\s*\\n|$)`),
  );
  return match?.[1]?.trim() ?? "";
}

function originalRetrievalQuery(text) {
  return (
    promptSection(text, "original user query")
    || promptSection(text, "original query")
    || "AgentMesh knowledge marker"
  );
}

function modelFixtureReply(body, desktopRoot) {
  const messages = Array.isArray(body.messages) ? body.messages : [];
  const all = flattenedMessageText(messages);
  const user = lastUserText(messages);

  if (all.includes("Compress an OLD range of one conversation into a durable memory capsule.")) {
    return {
      content: JSON.stringify({
        summary: "P20 durable conversation history was compacted into a bounded memory capsule.",
        facts: ["Raw conversation history remains authoritative in MySQL."],
        decisions: ["Redis is only bounded working memory."],
        open_tasks: ["Continue P20 reliability validation."],
        entities: ["AgentMesh", "Redis", "MySQL"],
        keywords: ["conversation", "memory", "durability"],
        importance: 0.92,
      }),
    };
  }

  if (all.includes("[operation]\nrewrite")) {
    const query = originalRetrievalQuery(all);
    return { content: JSON.stringify({ query }) };
  }
  if (all.includes("[operation]\nmulti_query")) {
    const query = originalRetrievalQuery(all);
    return { content: JSON.stringify({ queries: [query, `${query} supporting evidence`] }) };
  }
  if (all.includes("[operation]\ndecompose")) {
    const query = originalRetrievalQuery(all);
    return { content: JSON.stringify({ queries: [query] }) };
  }
  if (all.includes('"sufficient"') && all.includes("evidence")) {
    return { content: JSON.stringify({ relevance: 0.99, coverage: 0.99, confidence: 0.99, sufficient: true, reason: "fixture evidence is sufficient" }) };
  }

  // The fixture must obey the SAME citation policy as a real model. Read a
  // marker only from an actual Retrieved Knowledge evidence item and use that
  // item's declared/available request-local citation. Never force [1] or
  // bypass Citation Guard when the model lacks usable evidence.
  const knowledgeReply = groundedFixtureKnowledgeReply(messages);
  if (knowledgeReply) return knowledgeReply;

  const tools = Array.isArray(body.tools) ? body.tools : [];
  const hasDesktopList = tools.some((item) => item?.function?.name === "local.fs.list");
  const toolMessage = [...messages].reverse().find((item) => item?.role === "tool");
  if (hasDesktopList && !toolMessage) {
    return {
      content: null,
      tool_calls: [{
        id: `call_v41_${Date.now()}`,
        type: "function",
        function: { name: "local.fs.list", arguments: JSON.stringify({ path: desktopRoot, limit: 50 }) },
      }],
    };
  }
  if (toolMessage) {
    const toolText = typeof toolMessage.content === "string" ? toolMessage.content : JSON.stringify(toolMessage.content ?? "");
    if (/"ok"\s*:\s*false|unavailable|permission_denied|authorization|unauthorized|授权|不可用/i.test(toolText)) {
      return { content: "桌面只读能力当前不可用或未获授权，请检查 Desktop Bridge 与授权目录后重试。" };
    }
    const desktopMarker = toolText.match(/AGENTMESH_V41_DESKTOP_[A-Z0-9_.\-]+/i)?.[0];
    return { content: desktopMarker ? `授权测试目录包含文件 ${desktopMarker}。` : "已完成本机只读目录查看。" };
  }

  const delayed = user.match(/FIX4_DELAY_[A-Z0-9_\-]+/i)?.[0];
  if (delayed) return { content: `FIX4_DELAY_REPLY_${delayed}` };
  const marker = user.match(/FIX4_[AB]_[A-Z0-9_\-]+/i)?.[0];
  if (marker) return { content: `FIX4_REPLY_${marker}` };
  return { content: "AgentMesh V4.1 deterministic browser fixture response." };
}

async function startModelFixture(port, desktopRoot) {
  let waiting = false;
  let release;
  const gate = () => new Promise((resolve) => { release = resolve; });
  let waitPromise = null;
  let holdMarker = "";
  let requestCount = 0;
  let lastUser = "";
  let lastMessageText = "";
  // QA-local, bounded structural diagnostics: no prompts, evidence text,
  // source paths, marker values, credentials or document identities.
  const knowledgeProbes = [];

  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url ?? "/", `http://${loopback}:${port}`);
    if (req.method === "GET" && url.pathname === "/health") {
      res.writeHead(200, { "content-type": "application/json" }); res.end('{"ok":true}'); return;
    }
    if (req.method === "GET" && url.pathname === "/control/state") {
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify({ waiting, holdMarker, requestCount, lastUser, lastMessageText, knowledgeProbes }));
      return;
    }
    if (req.method === "POST" && url.pathname === "/control/hold") {
      let raw = "";
      for await (const chunk of req) raw += String(chunk);
      const body = JSON.parse(raw || "{}");
      holdMarker = String(body.marker ?? "").trim();
      if (!holdMarker) {
        res.writeHead(400, { "content-type": "application/json" });
        res.end('{"ok":false,"error":"marker is required"}');
        return;
      }
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify({ ok: true, holdMarker }));
      return;
    }
    if (req.method === "POST" && url.pathname === "/control/release") {
      release?.(); release = undefined; waiting = false; waitPromise = null; holdMarker = "";
      res.writeHead(200, { "content-type": "application/json" }); res.end('{"ok":true}'); return;
    }
    if (req.method !== "POST" || url.pathname !== "/v1/chat/completions") {
      res.writeHead(404); res.end(); return;
    }
    let raw = "";
    for await (const chunk of req) raw += String(chunk);
    const body = JSON.parse(raw || "{}");
    const messages = Array.isArray(body.messages) ? body.messages : [];
    const user = lastUserText(messages);
    const all = flattenedMessageText(messages);
    requestCount += 1;
    lastUser = user;
    lastMessageText = all;
    if (holdMarker && all.includes(holdMarker)) {
      waiting = true;
      waitPromise ??= gate();
      await waitPromise;
    }
    const reply = modelFixtureReply(body, desktopRoot);
    const globalProbe = probeFixtureKnowledgeEvidence(messages, "GLOBAL");
    const projectProbe = probeFixtureKnowledgeEvidence(messages, "PROJECT");
    knowledgeProbes.push({
      requestIndex: requestCount,
      global: globalProbe.diagnostic,
      project: projectProbe.diagnostic,
      replyKind: globalProbe.evidence && reply.content?.includes(globalProbe.evidence.marker)
        ? "global_grounded"
        : projectProbe.evidence && reply.content?.includes(projectProbe.evidence.marker)
          ? "project_grounded" : reply.tool_calls ? "tool_call"
            : reply.content === "AgentMesh V4.1 deterministic browser fixture response."
              ? "generic" : "other",
    });
    if (knowledgeProbes.length > 32) knowledgeProbes.shift();
    const id = `chatcmpl-v41-${Date.now()}`;
    if (body.stream === true) {
      res.writeHead(200, { "content-type": "text/event-stream", "cache-control": "no-cache", connection: "keep-alive" });
      const content = String(reply.content ?? "");
      if (content) {
        res.write(`data: ${JSON.stringify({ id, object: "chat.completion.chunk", created: Math.floor(Date.now()/1000), model: "v4-1-e2e", choices: [{ index: 0, delta: { content }, finish_reason: null }] })}\n\n`);
      }
      res.write(`data: ${JSON.stringify({ id, object: "chat.completion.chunk", created: Math.floor(Date.now()/1000), model: "v4-1-e2e", choices: [{ index: 0, delta: {}, finish_reason: "stop" }] })}\n\n`);
      res.write("data: [DONE]\n\n"); res.end(); return;
    }
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify({
      id, object: "chat.completion", created: Math.floor(Date.now()/1000), model: "v4-1-e2e",
      choices: [{ index: 0, message: { role: "assistant", content: reply.content ?? null, ...(reply.tool_calls ? { tool_calls: reply.tool_calls } : {}) }, finish_reason: reply.tool_calls ? "tool_calls" : "stop" }],
      usage: { prompt_tokens: 32, completion_tokens: 16, total_tokens: 48 },
    }));
  });
  await new Promise((resolve, reject) => { server.once("error", reject); server.listen(port, loopback, resolve); });
  return server;
}

async function closeServer(server) {
  if (!server) return;
  await new Promise((resolve) => server.close(() => resolve()));
}

function resolvePython(root, envName) {
  const explicit = process.env[envName];
  if (explicit) return explicit;
  const candidates = process.platform === "win32"
    ? [path.join(root, ".venv", "Scripts", "python.exe"), "python"]
    : [path.join(root, ".venv", "bin", "python"), "python3", "python"];
  return candidates.find((candidate) => candidate === "python" || candidate === "python3" || fs.existsSync(candidate)) ?? candidates.at(-1);
}

async function runV41() {
  if (!process.env.P2_TEST_MYSQL_DSN) throw new Error("P2_TEST_MYSQL_DSN is required for V4.1 real-stack browser acceptance");

  const runtimeRoot = path.join(projectRoot, "runtime-python");
  const desktopRootProject = path.join(projectRoot, "desktop-bridge");
  const viteEntry = path.join(webRoot, "node_modules", "vite", "bin", "vite.js");
  if (!fs.existsSync(viteEntry)) throw new Error(`Vite entry not found: ${viteEntry}`);
  if (!fs.existsSync(runtimeRoot)) throw new Error(`runtime-python not found: ${runtimeRoot}`);
  if (!fs.existsSync(desktopRootProject)) throw new Error(`desktop-bridge not found: ${desktopRootProject}`);

  const fixture = await runFixture("prepare");
  const backendPort = await freePort();
  const frontPort = await freePort();
  const runtimePort = await freePort();
  const desktopPort = await freePort();
  const modelPort = await freePort();
  const debugPort = await freePort();
  const profile = fs.mkdtempSync(path.join(process.cwd(), ".v4-1-browser-"));
  const knowledgeRoot = fs.mkdtempSync(path.join(process.cwd(), ".v4-1-knowledge-"));
  const desktopFixtureRoot = fs.mkdtempSync(path.join(process.cwd(), ".v4-1-desktop-"));
  const stamp = String(Date.now());
  const desktopMarker = `AGENTMESH_V41_DESKTOP_${stamp}.txt`;
  fs.writeFileSync(path.join(desktopFixtureRoot, desktopMarker), "desktop read-only fixture", "utf8");
  const globalMarker = `AGENTMESH_V41_GLOBAL_${stamp}`;
  const globalKnowledgePrompt = "请根据我已经上传的个人资料，告诉我用户 A 的测试标记是什么？";
  const globalSecret = `PRIVATE_SECRET_SHOULD_NOT_TRACE_${stamp}`;
  const projectMarker = `AGENTMESH_V41_PROJECT_${stamp}`;
  const ownerA = { email: `v41-owner-a-${stamp}@example.test`, password: "V41OwnerAPass!123", displayName: "V41 Browser A", logs: () => serverLog };
  const ownerB = { email: `v41-owner-b-${stamp}@example.test`, password: "V41OwnerBPass!123", displayName: "V41 Browser B", logs: () => serverLog };
  const runtimeToken = "v4-1-browser-runtime-token-0123456789";
  const desktopToken = "v4-1-browser-desktop-token-0123456789";

  const milvusUri = process.env.V4_1_E2E_MILVUS_URI || "http://127.0.0.1:19530";
  const denseCollection = process.env.V4_1_E2E_MILVUS_COLLECTION || `agentmesh_v41_e2e_dense_${stamp}`;
  const hybridCollection = process.env.V4_1_E2E_MILVUS_HYBRID_COLLECTION || `agentmesh_v41_e2e_hybrid_${stamp}`;

  // FIX19: the Go fixture already uses an isolated Redis DB (13), but the
  // Python Runtime previously inherited config.py's default DB 0. Fresh QA
  // MySQL databases reuse small user/conversation ids, so a persistent DB 0
  // could make a new (user=2, conversation=5) consume an earlier run's short
  // term memory. Give Runtime its own QA Redis DB and a per-run namespace.
  const runtimeRedisUrl = process.env.V4_1_E2E_RUNTIME_REDIS_URL || "redis://127.0.0.1:6382/14";
  const runtimeRedisDb = redisDatabaseFromUrl(runtimeRedisUrl);
  if (runtimeRedisDb === 0) {
    throw new Error("V4.1 Runtime Redis must use an isolated non-zero DB; DB 0 is reserved for normal development/runtime state");
  }
  const runtimeMemoryPrefix = `agentmesh:v4-1:e2e:${stamp}:memory`;

  let serverLog = "";
  let runtimeLog = "";
  let desktopLog = "";
  let goServer; let runtime; let desktop; let vite; let browserChild; let cdp; let modelServer;
  let runtimePython = "";
  let latestAccessToken = "";
  const globalKnowledgeSubmissions = [];
  let tokenA = "";
  let apiBase = "";
  let globalFixture = null;
  let projectKnowledgeFixture = null;
  let project = null;
  let cleanupError; let primaryError;
  try {
    modelServer = await startModelFixture(modelPort, desktopFixtureRoot);

    const desktopPython = resolvePython(desktopRootProject, "V4_1_E2E_DESKTOP_PYTHON");
    desktop = spawn(desktopPython, ["-m", "uvicorn", process.env.V4_1_E2E_DESKTOP_APP || "desktop_bridge.app:app", "--host", loopback, "--port", String(desktopPort)], {
      cwd: desktopRootProject,
      env: {
        ...process.env,
        DESKTOP_TOKEN: desktopToken,
        DESKTOP_BRIDGE_TOKEN: desktopToken,
        AGENTMESH_DESKTOP_TOKEN: desktopToken,
        // Desktop Bridge reads the authoritative allowlist from
        // DESKTOP_ALLOWED_ROOTS_JSON. Keep this as a JSON array so paths
        // containing spaces/backslashes remain unambiguous on Windows.
        DESKTOP_ALLOWED_ROOTS_JSON: JSON.stringify([desktopFixtureRoot]),
      },
      stdio: ["ignore", "pipe", "pipe"],
    });
    desktop.stdout?.on("data", (chunk) => { desktopLog += String(chunk); });
    desktop.stderr?.on("data", (chunk) => { desktopLog += String(chunk); });
    await waitForUrl(`http://${loopback}:${desktopPort}/health`, 30000);
    const desktopProbe = await fetch(`http://${loopback}:${desktopPort}/v1/files/list`, {
      method: "POST",
      headers: { "content-type": "application/json", "x-desktop-token": desktopToken },
      body: JSON.stringify({ path: desktopFixtureRoot, limit: 10 }),
    });
    if (!desktopProbe.ok) {
      throw new Error(`real Desktop Bridge preflight failed: HTTP ${desktopProbe.status} ${await desktopProbe.text()}`);
    }

    runtimePython = resolvePython(runtimeRoot, "V4_1_E2E_RUNTIME_PYTHON");
    // Validate connectivity and clear only this run's namespace. The prefix is
    // unique already, so this is hygiene rather than correctness; no FLUSHDB
    // or FLUSHALL is ever used.
    await cleanupRuntimeMemory(runtimePython, runtimeRoot, runtimeRedisUrl, runtimeMemoryPrefix);

    runtime = spawn(runtimePython, ["-m", "uvicorn", "app.main:app", "--host", loopback, "--port", String(runtimePort)], {
      cwd: runtimeRoot,
      env: {
        ...process.env,
        RUNTIME_PORT: String(runtimePort),
        INTERNAL_TOKEN: runtimeToken,
        MODEL_PROVIDER: "openai_compatible",
        MODEL_API_KEY: "v4-1-e2e-model-key",
        MODEL_BASE_URL: `http://${loopback}:${modelPort}/v1`,
        MODEL_NAME: "v4-1-e2e",
        MODEL_VISION_NAME: "v4-1-e2e",
        MODEL_HTTP_TRUST_ENV: "false",
        MODEL_ROUTER_ENABLED: "false",
        EVAL_SCORECARD_ENABLED: "false",
        RUNTIME_WORKER_ENABLED: "false",
        CONTROL_PLANE_INTERNAL_BASE_URL: `http://${loopback}:${backendPort}`,
        AGENTMESH_CONTROL_PLANE_URL: `http://${loopback}:${backendPort}`,
        DESKTOP_BRIDGE_ENABLED: "true",
        DESKTOP_BRIDGE_BASE_URL: `http://${loopback}:${desktopPort}`,
        DESKTOP_BRIDGE_TOKEN: desktopToken,
        RAG_BACKEND: process.env.V4_1_E2E_RAG_BACKEND || "hybrid_milvus",
        MILVUS_URI: milvusUri,
        MILVUS_COLLECTION: denseCollection,
        MILVUS_HYBRID_COLLECTION: hybridCollection,
        REDIS_URL: runtimeRedisUrl,
        MEMORY_BACKEND: "redis",
        MEMORY_KEY_PREFIX: runtimeMemoryPrefix,
      },
      stdio: ["ignore", "pipe", "pipe"],
    });
    runtime.stdout?.on("data", (chunk) => { runtimeLog += String(chunk); });
    runtime.stderr?.on("data", (chunk) => { runtimeLog += String(chunk); });

    goServer = spawn("go", ["run", "./cmd/server"], {
      cwd: backendRoot,
      env: {
        ...process.env,
        BUSINESS_PORT: String(backendPort),
        MYSQL_HOST: fixture.host, MYSQL_PORT: fixture.port, MYSQL_DATABASE: fixture.database, MYSQL_USER: fixture.user, MYSQL_PASSWORD: fixture.password,
        REDIS_ADDR: process.env.V4_1_E2E_REDIS_ADDR || process.env.P12_E2E_REDIS_ADDR || "127.0.0.1:6382",
        REDIS_PASSWORD: process.env.V4_1_E2E_REDIS_PASSWORD || process.env.P12_E2E_REDIS_PASSWORD || "",
        REDIS_DB: process.env.V4_1_E2E_REDIS_DB || "13",
        JWT_SECRET: "v4-1-browser-jwt-secret-0123456789abcdef", JWT_ISSUER: "agentmesh-v4-1-browser", JWT_ACCESS_TTL_MINUTES: "30", JWT_REFRESH_TTL_DAYS: "3",
        AUTH_REFRESH_COOKIE_NAME: "refresh_token", AUTH_COOKIE_SECURE: "false",
        RUNTIME_BASE_URL: `http://${loopback}:${runtimePort}`, RUNTIME_INTERNAL_TOKEN: runtimeToken, RUNTIME_TIMEOUT_SECONDS: "60",
        MCP_DEMO_ENDPOINT: "http://127.0.0.1:1/mcp", ALLOWED_ORIGINS: `http://127.0.0.1:${frontPort}`,
        TASK_RATE_LIMIT_PER_MINUTE: "1000", DURABLE_RUNTIME_ENABLED: "false", GOVERNANCE_MASTER_KEY: "v4-1-browser-governance-key-0123456789",
        VERIFICATION_PEPPER: "v4-1-browser-verification-pepper-123", VERIFICATION_COOLDOWN_SECONDS: "1", EMAIL_PROVIDER: "console", KNOWLEDGE_STORAGE_ROOT: knowledgeRoot,
      },
      stdio: ["ignore", "pipe", "pipe"],
    });
    goServer.stdout?.on("data", (chunk) => { serverLog += String(chunk); });
    goServer.stderr?.on("data", (chunk) => { serverLog += String(chunk); });
    await waitForUrl(`http://${loopback}:${backendPort}/health`, 45000);
    await waitForUrl(`http://${loopback}:${runtimePort}/readyz`, 45000);

    vite = spawn(process.execPath, [viteEntry, "--host", "0.0.0.0", "--port", String(frontPort)], {
      cwd: webRoot, env: { ...process.env, VITE_DEV_PROXY_TARGET: `http://${loopback}:${backendPort}` }, stdio: ["ignore", "pipe", "pipe"],
    });
    await waitForUrl(`http://${loopback}:${frontPort}`, 30000);

    const browser = resolveBrowser();
    browserChild = spawn(browser, ["--headless=new", "--window-size=1440,1000", "--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage", "--remote-allow-origins=*", `--remote-debugging-port=${debugPort}`, `--user-data-dir=${profile}`, "about:blank"], { stdio: "ignore" });
    const page = await waitForPageTarget(debugPort);
    cdp = new CDP(page.webSocketDebuggerUrl); await cdp.connect();
    await cdp.send("Runtime.enable"); await cdp.send("Page.enable");
    // Keep POST bodies available to the event only for the strict, redacted
    // per-request policy assertion; never persist or print the raw body.
    await cdp.send("Network.enable", { maxPostDataSize: 65536 });
    await cdp.send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
    cdp.on("Network.requestWillBeSent", ({ request }) => {
      const auth = request?.headers?.Authorization ?? request?.headers?.authorization;
      if (typeof auth === "string" && /^Bearer\s+/.test(auth)) latestAccessToken = auth.replace(/^Bearer\s+/i, "");
      const policy = summarizeGlobalKnowledgeSubmission(request, globalKnowledgePrompt);
      if (policy) globalKnowledgeSubmissions.push(policy);
    });

    const frontUrl = `http://${loopback}:${frontPort}`;
    apiBase = `http://${loopback}:${backendPort}`;
    await cdp.send("Page.navigate", { url: frontUrl });
    await registerOwner(cdp, ownerA);
    tokenA = await waitForAccessToken(() => latestAccessToken);
    await verifyAndReloadV41ModelService(cdp, fixture, apiBase, tokenA, ownerA.email, ownerA.displayName, modelPort);

    // P20 light-theme regression: project management controls must stay on the
    // light surface even if legacy/global form rules still exist elsewhere.
    await openCreateProjectWhenReady(cdp);
    await waitFor(cdp, `document.querySelector('[data-testid="project-name-input"]')`, "create-project name input");
    const projectControlTheme = await cdp.evaluate(`(() => {
      const input=document.querySelector('[data-testid="project-name-input"]');
      const textarea=input?.closest('form')?.querySelector('textarea');
      const parse=(value)=>{ const xs=String(value||'').match(/[0-9.]+/g)?.map(Number)??[]; return xs.slice(0,3); };
      return { inputBg: parse(getComputedStyle(input).backgroundColor), textareaBg: parse(getComputedStyle(textarea).backgroundColor) };
    })()`);
    assert.ok(projectControlTheme.inputBg.length === 3 && projectControlTheme.inputBg.every((value) => value >= 220), `project name input is not a light surface: ${JSON.stringify(projectControlTheme)}`);
    assert.ok(projectControlTheme.textareaBg.length === 3 && projectControlTheme.textareaBg.every((value) => value >= 220), `project description textarea is not a light surface: ${JSON.stringify(projectControlTheme)}`);
    await clickText(cdp, "取消");

    // P20 Conversation Memory Reliability: one real-stack scenario closes the
    // durability loop end-to-end while the canonical stack is still alive.
    // It deliberately combines browser pagination, Runtime compaction, bounded
    // Redis working memory, Redis namespace loss, internal-token authorization,
    // cross-user isolation and durable MySQL capsule/history recovery.
    const p20History = await runP20MemoryFixture("seed-history", [
      "--database", fixture.database,
      "--email", ownerA.email,
      "--count", "125",
      "--marker-prefix", `P20_HISTORY_${stamp}`,
    ]);
    await cdp.send("Page.reload", { ignoreCache: true });
    await waitFor(cdp, `document.querySelector('.app-shell')`, "P20 durable-history reload", 20000);
    await openConversation(cdp, p20History.conversationId);
    await assertConversationAtBottom(cdp, "P20 durable-history open");
    await loadOneOlderPagePreservingViewport(cdp);
    await loadAllConversationHistory(cdp, 125);
    let p20HistorySnapshot = await durableMessageSnapshot(cdp);
    const initialHistoryEvidence = p20HistoryEvidence(
      "rendered-history",
      p20HistorySnapshot,
      p20History.firstMarker,
      p20History.lastMarker,
    );
    assert.ok(
      initialHistoryEvidence.count >= 125,
      `browser rendered fewer than 125 durable P20 messages: ${JSON.stringify(initialHistoryEvidence)}`,
    );
    assert.ok(
      initialHistoryEvidence.firstMarker,
      `browser could not reach first durable P20 message: ${JSON.stringify(initialHistoryEvidence)}`,
    );
    assert.ok(
      initialHistoryEvidence.lastMarker,
      `browser could not reach last durable P20 message: ${JSON.stringify(initialHistoryEvidence)}`,
    );

    const capsuleRoute = `/internal/v1/users/${p20History.userId}/conversations/${p20History.conversationId}/memory-capsules?limit=20`;
    assert.equal((await internalMemoryRequest(apiBase, "", "GET", capsuleRoute)).response.status, 401, "missing internal token must be rejected");
    assert.equal((await internalMemoryRequest(apiBase, "wrong-p20-internal-token", "GET", capsuleRoute)).response.status, 401, "wrong internal token must be rejected");

    const beforeCompactionRefresh = p20HistorySnapshot;
    const compactionPrompt = `P20_MEMORY_COMPACTION_TRIGGER_${stamp}`;
    await sendPrompt(cdp, compactionPrompt);
    const afterSameConversationRefresh = await durableMessageSnapshot(cdp);
    const sameConversationEvidence = p20HistoryEvidence(
      "same-conversation-refresh",
      afterSameConversationRefresh,
      p20History.firstMarker,
      p20History.lastMarker,
    );
    console.log(
      `[P20] same-conversation-refresh counts ${JSON.stringify({
        before: beforeCompactionRefresh.count,
        after: afterSameConversationRefresh.count,
        compactionPromptPresent: afterSameConversationRefresh.texts.some((value) => value.includes(compactionPrompt)),
      })}`,
    );
    assert.ok(
      sameConversationEvidence.firstMarker,
      `same-conversation refresh collapsed the expanded durable history window: ${JSON.stringify(sameConversationEvidence)}`,
    );
    assert.ok(
      sameConversationEvidence.lastMarker,
      `same-conversation refresh lost the newest durable marker: ${JSON.stringify(sameConversationEvidence)}`,
    );
    assert.ok(
      afterSameConversationRefresh.texts.some((value) => value.includes(compactionPrompt)),
      `same-conversation refresh lost the compaction-trigger prompt: ${JSON.stringify(sameConversationEvidence)}`,
    );
    const capsules = await waitForConversationCapsules(
      apiBase, runtimeToken, p20History.userId, p20History.conversationId, 30000,
    );
    const capsule = capsules[0];
    assert.ok(Number(capsule?.id) > 0, "Runtime did not persist a real conversation memory capsule");
    console.log(
      `[P20] memory-capsule ${JSON.stringify({
        capsuleId: Number(capsule.id),
        conversationId: Number(p20History.conversationId),
        startMessageId: Number(capsule.startMessageId),
        endMessageId: Number(capsule.endMessageId),
      })}`,
    );

    const crossUser = await internalMemoryRequest(
      apiBase, runtimeToken, "GET",
      `/internal/v1/users/${Number(p20History.userId) + 1000000}/conversations/${p20History.conversationId}/memory-capsules?limit=20`,
    );
    assert.equal(crossUser.response.status, 404, "cross-user capsule access must fail closed");

    const capsuleWrite = {
      startMessageId: capsule.startMessageId,
      endMessageId: capsule.endMessageId,
      summary: capsule.summary,
      facts: capsule.facts ?? [],
      decisions: capsule.decisions ?? [],
      openTasks: capsule.openTasks ?? [],
      entities: capsule.entities ?? [],
      keywords: capsule.keywords ?? [],
      importance: capsule.importance,
      sourceHash: capsule.sourceHash,
      compactionModel: capsule.compactionModel ?? "",
      inputTokens: capsule.inputTokens ?? 0,
      outputTokens: capsule.outputTokens ?? 0,
      estimatedCost: capsule.estimatedCost ?? null,
    };
    const beforeIdempotentCount = capsules.length;
    for (let index = 0; index < 2; index += 1) {
      const upserted = await internalMemoryRequest(
        apiBase, runtimeToken, "POST",
        `/internal/v1/users/${p20History.userId}/conversations/${p20History.conversationId}/memory-capsules`,
        capsuleWrite,
      );
      assert.equal(upserted.response.ok, true, `idempotent capsule upsert ${index + 1} failed: ${JSON.stringify(upserted.payload)}`);
    }
    const afterIdempotent = await internalMemoryRequest(apiBase, runtimeToken, "GET", capsuleRoute);
    assert.equal(afterIdempotent.response.ok, true);
    assert.equal(afterIdempotent.data.length, beforeIdempotentCount, "same capsule range must upsert idempotently");

    const redisBeforeClear = await inspectRuntimeMemory(runtimePython, runtimeRoot, runtimeRedisUrl, runtimeMemoryPrefix);
    console.log(
      `[P20] redis-working-memory ${JSON.stringify({
        maxListLength: redisBeforeClear.maxListLength,
        keyCount: redisBeforeClear.items.length,
      })}`,
    );
    assert.ok(redisBeforeClear.maxListLength <= 20, `Runtime Redis working list exceeded 20 messages: ${JSON.stringify(redisBeforeClear)}`);
    await cleanupRuntimeMemory(runtimePython, runtimeRoot, runtimeRedisUrl, runtimeMemoryPrefix);
    const redisAfterClear = await inspectRuntimeMemory(runtimePython, runtimeRoot, runtimeRedisUrl, runtimeMemoryPrefix);
    assert.equal(redisAfterClear.items.length, 0, "isolated P20 Runtime Redis namespace was not cleared");

    await cdp.send("Page.reload", { ignoreCache: true });
    await waitFor(cdp, `document.querySelector('.app-shell')`, "P20 post-Redis-clear reload", 20000);
    await openConversation(cdp, p20History.conversationId);
    await assertConversationAtBottom(cdp, "P20 post-Redis-clear conversation restore");
    await loadAllConversationHistory(cdp, 125);
    p20HistorySnapshot = await durableMessageSnapshot(cdp);
    const postRedisHistoryEvidence = p20HistoryEvidence(
      "post-redis-clear-history",
      p20HistorySnapshot,
      p20History.firstMarker,
      p20History.lastMarker,
    );
    assert.ok(
      postRedisHistoryEvidence.count >= 125,
      `fewer than 125 durable messages remained after Redis clear: ${JSON.stringify(postRedisHistoryEvidence)}`,
    );
    assert.ok(
      postRedisHistoryEvidence.firstMarker,
      `first durable message disappeared after Redis clear: ${JSON.stringify(postRedisHistoryEvidence)}`,
    );
    assert.ok(
      postRedisHistoryEvidence.lastMarker,
      `last durable message disappeared after Redis clear: ${JSON.stringify(postRedisHistoryEvidence)}`,
    );
    const capsulesAfterRedisClear = await internalMemoryRequest(apiBase, runtimeToken, "GET", capsuleRoute);
    assert.equal(capsulesAfterRedisClear.response.ok, true);
    assert.ok(Array.isArray(capsulesAfterRedisClear.data) && capsulesAfterRedisClear.data.length >= 1, "MySQL capsule disappeared after Redis clear");
    console.log(
      `[P20] redis-loss-recovery ${JSON.stringify({
        recoveredCount: postRedisHistoryEvidence.count,
        firstMarker: postRedisHistoryEvidence.firstMarker,
        lastMarker: postRedisHistoryEvidence.lastMarker,
        capsuleCount: capsulesAfterRedisClear.data.length,
      })}`,
    );

    // 1) New-conversation isolation, including late-response ownership.
    const convA = await createConversationThroughBrowser(cdp);
    const aMarker = `FIX4_A_${stamp}`;
    await sendPrompt(cdp, aMarker, `FIX4_REPLY_${aMarker}`);
    const draftA = `UNSENT_A_${stamp}`;
    await setValue(cdp, '[data-testid="workspace-composer"]', draftA);
    const convB = await createConversationThroughBrowser(cdp);
    assert.equal(await composerValue(cdp), "", "conversation B must not inherit A draft");
    assert.ok(!(await workspaceText(cdp)).includes(aMarker), "conversation B leaked A message");

    const delayedMarker = `FIX4_DELAY_${stamp}`;
    await setValue(cdp, '[data-testid="workspace-composer"]', delayedMarker);
    // sendPrompt() returns as soon as assistant text is visible, while the prior
    // request can still be inside its final reload/finally path. Workspace
    // intentionally disables submit while busy, so clicking immediately here
    // can be a no-op. Wait for the real product button to become actionable.
    await waitFor(
      cdp,
      `document.querySelector('[data-testid="workspace-submit"]')?.disabled === false`,
      "delayed B submit enabled",
      30000,
    );
    const modelStateUrl = `http://${loopback}:${modelPort}/control/state`;
    const holdResponse = await fetch(`http://${loopback}:${modelPort}/control/hold`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ marker: delayedMarker }),
    });
    assert.equal(holdResponse.ok, true, `failed to arm delayed model fixture: HTTP ${holdResponse.status}`);
    await clickSelector(cdp, '[data-testid="workspace-submit"]', "delayed B submit");
    await waitFor(
      cdp,
      `[...document.querySelectorAll('[data-testid="message-user"], [data-testid="message-user-optimistic"]')].some((el)=>el.textContent?.includes(${q(delayedMarker)}))`,
      "delayed B user prompt",
      15000,
    );
    const waitDeadline = Date.now() + 20000;
    let delayedState = await (await fetch(modelStateUrl)).json();
    while (Date.now() < waitDeadline) {
      delayedState = await (await fetch(modelStateUrl)).json();
      if (delayedState.waiting && String(delayedState.lastMessageText ?? "").includes(delayedMarker)) break;
      await sleep(100);
    }
    assert.equal(
      delayedState.waiting && String(delayedState.lastMessageText ?? "").includes(delayedMarker),
      true,
      `delayed model request never reached armed fixture; state=${JSON.stringify(delayedState)}`,
    );
    await openConversation(cdp, convA);
    await fetch(`http://${loopback}:${modelPort}/control/release`, { method: "POST" });
    await sleep(1200);
    assert.ok(!(await workspaceText(cdp)).includes(`FIX4_DELAY_REPLY_${delayedMarker}`), "late B response overwrote active conversation A");
    await openConversation(cdp, convB);
    await waitFor(cdp, `[...document.querySelectorAll('[data-testid="message-assistant"]')].some((el)=>el.textContent?.includes(${q(`FIX4_DELAY_REPLY_${delayedMarker}`)}))`, "B delayed persisted response", 30000);
    await cdp.send("Page.reload", { ignoreCache: true });
    await waitFor(cdp, `document.querySelector('.app-shell')`, "session after conversation isolation reload", 20000);
    await openConversation(cdp, convB);
    assert.ok((await workspaceText(cdp)).includes(`FIX4_DELAY_REPLY_${delayedMarker}`), "B history missing after reload");

    // Close the reload-isolation loop in both directions. B surviving reload
    // is not enough: switch back to A and re-read authoritative history so a
    // stale/late B projection cannot be hidden by the fact that B was active
    // at reload time.
    await openConversation(cdp, convA);
    await waitFor(
      cdp,
      `[...document.querySelectorAll('[data-testid="message-user"]')].some((el)=>el.textContent?.includes(${q(aMarker)}))`,
      "A authoritative user history after reload",
      20000,
    );
    await waitFor(
      cdp,
      `[...document.querySelectorAll('[data-testid="message-assistant"]')].some((el)=>el.textContent?.includes(${q(`FIX4_REPLY_${aMarker}`)}))`,
      "A authoritative assistant history after reload",
      20000,
    );
    const reloadedAText = await workspaceText(cdp);
    assert.ok(!reloadedAText.includes(delayedMarker), "B delayed user message leaked into A after reload");
    assert.ok(!reloadedAText.includes(`FIX4_DELAY_REPLY_${delayedMarker}`), "B delayed assistant response leaked into A after reload");

    // 2) Natural Desktop read-only success through the real Desktop Bridge.
    await createConversationThroughBrowser(cdp);
    const desktopPrompt = "请查看授权测试目录里有哪些文件，并告诉我文件名";
    await sendPrompt(cdp, desktopPrompt, desktopMarker, 90000);
    await openLatestRunDetails(cdp);
    await clickSelector(cdp, '[data-testid="run-details-tab-desktop"]', "desktop details tab");
    await waitFor(cdp, `document.querySelector('[data-testid="desktop-trace-event"][data-tool="local.fs.list"]')`, "local.fs.list trace");
    const desktopDrawer = await cdp.evaluate(`document.querySelector('[data-testid="run-details-drawer"]')?.innerText ?? ''`);
    assert.ok(!desktopDrawer.includes(desktopToken), "Desktop token leaked to trace UI");
    assert.ok(!desktopDrawer.includes("Bearer "), "bearer credential leaked to trace UI");
    await closeRunDetails(cdp);

    // Desktop unavailable must degrade to product-safe UX, never a raw HTTP 500.
    await stopChild(desktop); desktop = undefined;
    await createConversationThroughBrowser(cdp);
    await sendPrompt(cdp, "请再查看一次授权测试目录的文件列表");
    const failureText = await workspaceText(cdp);
    assert.ok(!/runtime returned 500 Internal Server Error|\bInternal Server Error\b/.test(failureText), `raw runtime 500 leaked to Workspace: ${failureText}`);
    assert.ok(
      failureText.includes("桌面只读能力当前不可用或未获授权"),
      `Desktop Bridge failure was not normalized into product-safe UX: ${failureText}`,
    );

    // 3) Natural GLOBAL Knowledge and isolation.
    globalFixture = await createKnowledgeFixture(apiBase, tokenA, {
      name: `V41 Global ${stamp}`, scope: "GLOBAL", filename: `global-${stamp}.txt`,
      content: `用户 A 的测试标记是 ${globalMarker}。\n这行是私密追踪哨兵：${globalSecret}。`,
    });
    assert.ok(globalFixture.base.id > 0);

    // Negative boundary first: upload/index success is NOT authorization.
    // A fresh non-project Workspace starts with PROJECT only. Verify both the
    // actual browser payload and the response cannot access the Global marker.
    await createConversationThroughBrowser(cdp);
    await sendPrompt(cdp, globalKnowledgePrompt);
    assertObservedGlobalKnowledgeSubmission(globalKnowledgeSubmissions, false, "A before global opt-in");
    assert.ok(!(await workspaceText(cdp)).includes(globalMarker), "GLOBAL Knowledge leaked without explicit user consent");

    // Positive boundary: explicitly enable the Global scope through the real
    // Run Settings UI. Do not select a KB: this must exercise AUTO discovery.
    await createConversationThroughBrowser(cdp);
    await setUserGlobalKnowledgeScope(cdp, true);
    const modelRequestsBeforeGlobal = (await (await fetch(`http://${loopback}:${modelPort}/control/state`)).json()).requestCount;
    try {
      await sendPrompt(cdp, globalKnowledgePrompt, globalMarker, 120000);
    } catch (error) {
      // Preserve the real failure. Output only boolean/count/policy metadata so
      // a future no-recall failure can be localized without dumping private
      // knowledge, prompt bodies, tokens or the fixture's secret sentinel.
      await reportFailurePreservingPrimary(error, "[P22 GLOBAL]", async () => {
        const state = await fetch(`http://${loopback}:${modelPort}/control/state`)
          .then((response) => response.json()).catch(() => null);
        return {
          requestPolicy: globalKnowledgeSubmissions.at(-1) ?? null,
          modelRequestsSinceSubmit: state ? state.requestCount - modelRequestsBeforeGlobal : null,
          lastModelContextHadGlobalMarker: Boolean(state?.lastMessageText?.includes(globalMarker)),
          // The old boolean only searched the whole request. This captures
          // the ACTUAL citation parser decision for every model call after
          // submission, so a memory marker cannot masquerade as evidence.
          knowledgeProbeChain: state?.knowledgeProbes?.filter(
            item => item.requestIndex > modelRequestsBeforeGlobal,
          ) ?? [],
          runDetailsOpenerPresent: await cdpElementExists(cdp, '[data-testid="run-details-open"]'),
        };
      });
    }
    assertObservedGlobalKnowledgeSubmission(globalKnowledgeSubmissions, true, "A after global opt-in");
    const globalProofs = (await (await fetch(`http://${loopback}:${modelPort}/control/state`)).json())
      .knowledgeProbes.filter(item => item.requestIndex > modelRequestsBeforeGlobal);
    assert.ok(
      globalProofs.some(item => item.global.reason === "valid_evidence" && item.replyKind === "global_grounded"),
      "GLOBAL marker in model request is not proof of a citation-grounded fixture response",
    );
    await openLatestRunDetails(cdp);
    await clickSelector(cdp, '[data-testid="run-details-tab-capability"]', "capability tab");
    await waitFor(cdp, `document.querySelector('[data-testid="capability-discovery-event"][data-knowledge-selected="true"]')`, "GLOBAL knowledge capability selection");
    const globalDrawer = await cdp.evaluate(`document.querySelector('[data-testid="run-details-drawer"]')?.innerText ?? ''`);
    assert.ok(!globalDrawer.includes(globalSecret), "raw private knowledge payload leaked to trace UI");
    await clickSelector(cdp, '[data-testid="run-details-tab-rag"]', "RAG tab");
    const ragText = await cdp.evaluate(`document.querySelector('[data-testid="run-details-drawer"]')?.innerText ?? ''`);
    assert.ok(/Retrieval|检索|RAG/i.test(ragText), "RAG execution evidence missing from Run Details");
    const retrievalHits = await cdp.evaluate(`Number(document.querySelectorAll('[data-testid="run-details-drawer"] .rag-summary-grid > div strong')[2]?.textContent?.trim() ?? 0)`);
    assert.ok(retrievalHits > 0, `Global Knowledge had no actual retrieval hits (Run Details hits=${retrievalHits})`);
    await closeRunDetails(cdp);
    console.log("[P22 E2E] GLOBAL positive retrieval gate PASS");

    // Negative routing: generic résumé writing must not force private retrieval.
    await createConversationThroughBrowser(cdp);
    await sendPrompt(cdp, "请写一份 Java 后端工程师求职简历模板");
    await openLatestRunDetails(cdp);
    await clickSelector(cdp, '[data-testid="run-details-tab-capability"]', "negative capability tab");
    const negativeSelected = await cdp.evaluate(`[...document.querySelectorAll('[data-testid="capability-discovery-event"]')].some((el)=>el.dataset.knowledgeSelected==='true')`);
    assert.equal(negativeSelected, false, "generic résumé-writing request unexpectedly forced private Knowledge retrieval");
    await closeRunDetails(cdp);

    // Project mode may use PROJECT KBs and explicitly bound GLOBAL KBs only.
    // Clear the previous user-consented Global scope before asserting the
    // unbound-Global isolation case. Keeping it enabled tests a different
    // contract and would be a false privacy regression.
    await setUserGlobalKnowledgeScope(cdp, false);
    project = await apiRequest(apiBase, tokenA, "POST", "/api/projects", JSON.stringify({ name: `V41 Project ${stamp}`, description: "browser isolation fixture" }), { "Content-Type": "application/json" });
    projectKnowledgeFixture = await createKnowledgeFixture(apiBase, tokenA, {
      name: `V41 Project KB ${stamp}`, scope: "PROJECT", projectId: project.id, filename: `project-${stamp}.txt`,
      content: `当前项目的测试标记是 ${projectMarker}。`,
    });
    console.log("[P22 E2E] PROJECT knowledge fixture indexed");
    const projectConv = await createConversationThroughBrowser(cdp);
    await apiRequest(apiBase, tokenA, "PUT", `/api/projects/${project.id}/conversations/${projectConv}`);
    await openConversation(cdp, projectConv);
    const modelRequestsBeforeProject = (await (await fetch(`http://${loopback}:${modelPort}/control/state`)).json()).requestCount;
    try {
      await sendPrompt(cdp, "请根据当前项目资料告诉我项目测试标记是什么？", projectMarker, 120000);
      const projectProofs = (await (await fetch(`http://${loopback}:${modelPort}/control/state`)).json())
        .knowledgeProbes.filter(item => item.requestIndex > modelRequestsBeforeProject);
      assert.ok(
        projectProofs.some(item => item.project.reason === "valid_evidence" && item.replyKind === "project_grounded"),
        "PROJECT marker in model request is not proof of a citation-grounded fixture response",
      );
      console.log("[P22 E2E] PROJECT grounded answer marker received");
    } catch (error) {
      // Preserve the original failure and emit only metadata. A future real
      // retrieval/projection defect must not be misclassified as this fixture
      // regression, and private knowledge must never be printed to QA logs.
      await reportFailurePreservingPrimary(error, "[P22 PROJECT]", async () => {
        const state = await fetch(`http://${loopback}:${modelPort}/control/state`)
          .then(response => response.json()).catch(() => null);
        let citation = null;
        try {
          await openLatestRunDetails(cdp);
          await clickSelector(cdp, '[data-testid="run-details-tab-rag"]', "failed project RAG details tab");
          citation = await cdp.evaluate(`(() => {
            const drawer=document.querySelector('[data-testid="run-details-drawer"]');
            const row=[...drawer.querySelectorAll('.timeline-item')].find(item=>item.querySelector('.timeline-header strong')?.textContent?.trim()==='Citation Guard');
            let guard=null;
            try { guard=JSON.parse(row?.querySelector('.timeline-body pre')?.textContent ?? 'null'); } catch {}
            return guard ? { passed:guard.passed===true, action:guard.action ?? null,
              violationTypes:Array.isArray(guard.violations) ? guard.violations.map(value=>String(value).split(':')[0]) : [],
              availableCount:Array.isArray(guard.availableCitations) ? guard.availableCitations.length : 0,
              usedCount:Array.isArray(guard.citations) ? guard.citations.length : 0 } : null;
          })()`);
          await closeRunDetails(cdp);
        } catch { /* Preserve original failure if optional Run Details inspection fails. */ }
        return {
          modelContextHadProjectMarker: Boolean(state?.lastMessageText?.includes(projectMarker)),
          modelContextHadKnowledge: Boolean(state?.lastMessageText?.includes('[Retrieved Knowledge]')),
          knowledgeProbeChain: state?.knowledgeProbes?.filter(
            item => item.requestIndex > modelRequestsBeforeProject,
          ) ?? [],
          browserShowsSafeRejection: (await workspaceText(cdp)).includes('证据引用未能通过校验'),
          citation,
        };
      });
    }
    // A bare marker is not success: a valid grounded answer must carry a
    // projected citation and the real Run Details must show guard=allow.
    // sendPrompt may observe the marker in a transient streaming answer before
    // the durable message and its citation metadata have been hydrated. Check
    // EVERY durable assistant row (not the first textContent match); require an
    // actual interactive marker and a matching source filename/label in that
    // SAME row. Visible text "[1]" plus a separate SOURCES card is not proof.
    try {
      await waitFor(
        cdp,
        projectCitationReadyExpression(projectMarker, `project-${stamp}.txt`),
        "PROJECT durable answer with clickable citation and matching source provenance",
        30000,
      );
    } catch (error) {
      await reportFailurePreservingPrimary(error, "[P22 PROJECT CITATION DOM]", async () =>
        cdp.evaluate(projectCitationDiagnosticExpression(projectMarker, `project-${stamp}.txt`)),
      );
    }
    await openLatestRunDetails(cdp);
    await clickSelector(cdp, '[data-testid="run-details-tab-rag"]', "project RAG details tab");
    const projectCitationEvidence = await cdp.evaluate(`(() => {
      const panel=document.querySelector('[data-testid="run-details-drawer"]');
      const cards=[...panel.querySelectorAll('.rag-summary-grid > div')];
      const count=(label)=>Number(cards.find(card=>card.querySelector('span')?.textContent?.trim()===label)?.querySelector('strong')?.textContent?.trim() ?? 0);
      const guard=[...panel.querySelectorAll('.timeline-item')].find(item=>item.querySelector('.timeline-header strong')?.textContent?.trim()==='Citation Guard');
      let decision=null;
      try { decision=JSON.parse(guard?.querySelector('.timeline-body pre')?.textContent ?? 'null'); } catch {}
      return { hits:count('Retrieval Hits'), used:count('Used Citations'), guardPassed:decision?.passed===true, guardAction:decision?.action ?? null };
    })()`);
    assert.ok(projectCitationEvidence.hits > 0, `PROJECT Knowledge had no actual retrieval hits: ${JSON.stringify(projectCitationEvidence)}`);
    assert.ok(projectCitationEvidence.used > 0, `PROJECT Knowledge had no projected used citations: ${JSON.stringify(projectCitationEvidence)}`);
    assert.equal(projectCitationEvidence.guardPassed, true, `PROJECT citation guard must pass: ${JSON.stringify(projectCitationEvidence)}`);
    assert.equal(projectCitationEvidence.guardAction, 'allow', `PROJECT citation guard must allow: ${JSON.stringify(projectCitationEvidence)}`);
    console.log("[P22 E2E] PROJECT citation and provenance gate PASS");
    await closeRunDetails(cdp);
    const projectText = await workspaceText(cdp);
    assert.ok(!projectText.includes(globalMarker), "unbound GLOBAL Knowledge leaked into PROJECT conversation");

    // Remove user-owned Knowledge fixtures through production APIs before
    // switching identity. This exercises normal vector/file cleanup instead of
    // leaving acceptance data behind.
    await apiRequest(apiBase, tokenA, "DELETE", `/api/knowledge/bases/${projectKnowledgeFixture.base.id}`);
    projectKnowledgeFixture = null;
    await apiRequest(apiBase, tokenA, "DELETE", `/api/projects/${project.id}`);
    project = null;

    // Cross-user isolation: B must never retrieve A's GLOBAL marker while
    // User A's GLOBAL Knowledge still exists.
    await logoutAndAssert(cdp);
    latestAccessToken = "";
    await registerOwner(cdp, ownerB);
    const tokenB = await waitForAccessToken(() => latestAccessToken);
    await verifyAndReloadV41ModelService(cdp, fixture, apiBase, tokenB, ownerB.email, ownerB.displayName, modelPort);
    await createConversationThroughBrowser(cdp);
    // Stronger cross-user test: B opts in to B's own Global scope and still
    // cannot access A's globally indexed private data.
    await setUserGlobalKnowledgeScope(cdp, true);
    await sendPrompt(cdp, globalKnowledgePrompt);
    assertObservedGlobalKnowledgeSubmission(globalKnowledgeSubmissions, true, "B own global opt-in");
    const bText = await workspaceText(cdp);
    assert.ok(!bText.includes(globalMarker), "User B retrieved User A GLOBAL Knowledge marker");
    console.log("[P22 E2E] cross-user Global Knowledge isolation gate PASS");

    // Now that cross-user isolation has been proven with A's data present,
    // clean up A's GLOBAL fixture using the still-valid owner-A access token.
    await apiRequest(apiBase, tokenA, "DELETE", `/api/knowledge/bases/${globalFixture.base.id}`);
    globalFixture = null;

    console.log("AgentMesh V4.1 Real-stack Browser E2E: PASS");
  } catch (error) {
    primaryError = error;
  } finally {
    try { await withTimeout(closeBrowser(browserChild, cdp), 10000, "V4.1 browser cleanup"); } catch (error) { cleanupError ??= error; }

    // Best-effort production-API cleanup while the Go server and owner-A token
    // are still available. These branches matter only when the test fails
    // before the normal cleanup point above.
    if (apiBase && tokenA) {
      for (const fixtureItem of [projectKnowledgeFixture, globalFixture]) {
        if (!fixtureItem?.base?.id) continue;
        try {
          await withTimeout(
            apiRequest(apiBase, tokenA, "DELETE", `/api/knowledge/bases/${fixtureItem.base.id}`),
            15000,
            "V4.1 knowledge fixture cleanup",
          );
        } catch (error) {
          cleanupError ??= error;
        }
      }
      if (project?.id) {
        try {
          await withTimeout(
            apiRequest(apiBase, tokenA, "DELETE", `/api/projects/${project.id}`),
            15000,
            "V4.1 project fixture cleanup",
          );
        } catch (error) {
          cleanupError ??= error;
        }
      }
    }

    for (const [label, child] of [["Vite", vite], ["Go server", goServer], ["Runtime", runtime], ["Desktop Bridge", desktop]]) {
      try { await withTimeout(stopChild(child), 10000, `V4.1 ${label} cleanup`); } catch (error) { cleanupError ??= error; }
    }

    // FIX19: remove only this canonical run's short-term memory namespace.
    // A failed cleanup cannot cause cross-run contamination because the next
    // run receives a different prefix; recording the cleanup error still keeps
    // acceptance hygiene strict.
    if (runtimePython) {
      try {
        await withTimeout(
          cleanupRuntimeMemory(runtimePython, runtimeRoot, runtimeRedisUrl, runtimeMemoryPrefix),
          20000,
          "V4.1 Runtime Redis memory cleanup",
        );
      } catch (error) {
        cleanupError ??= error;
      }
    }

    // The harness uses unique Milvus collection names so concurrent/local runs
    // cannot collide. Drop them after Runtime shutdown as a final hygiene gate.
    if (runtimePython) {
      const cleanupScript = [
        "from pymilvus import MilvusClient",
        `client = MilvusClient(uri=${JSON.stringify(milvusUri)})`,
        `names = ${JSON.stringify([denseCollection, hybridCollection])}`,
        "for name in names:",
        "    try:",
        "        if client.has_collection(name):",
        "            client.drop_collection(name)",
        "    except Exception as exc:",
        "        raise RuntimeError(f'failed to drop {name}: {exc}') from exc",
      ].join("\n");
      try {
        await withTimeout(
          spawnCollected(runtimePython, ["-c", cleanupScript], { cwd: runtimeRoot, env: process.env }, 30000),
          35000,
          "V4.1 Milvus collection cleanup",
        );
      } catch (error) {
        cleanupError ??= error;
      }
    }

    try { await withTimeout(closeServer(modelServer), 5000, "V4.1 model fixture cleanup"); } catch (error) { cleanupError ??= error; }
    for (const dir of [profile, knowledgeRoot, desktopFixtureRoot]) {
      try { fs.rmSync(dir, { recursive: true, force: true }); } catch (error) { cleanupError ??= error; }
    }
    try { await withTimeout(runFixture("cleanup", ["--database", fixture.database]), 35000, "V4.1 fixture cleanup"); } catch (error) { cleanupError ??= error; }
  }

  if (primaryError) {
    if (serverLog) console.error(`V4.1 Go log:\n${redactQaDiagnostics(serverLog)}`);
    if (runtimeLog) console.error(`V4.1 Runtime log:\n${runtimeLog}`);
    if (desktopLog) console.error(`V4.1 Desktop log:\n${desktopLog}`);
    if (cleanupError) console.error(`V4.1 cleanup warning: ${cleanupError.stack ?? cleanupError}`);
    throw primaryError;
  }
  if (cleanupError) throw cleanupError;
}

try {
  await runV41();
  process.exit(0);
} catch (error) {
  console.error(error?.stack ?? error);
  process.exit(1);
}
