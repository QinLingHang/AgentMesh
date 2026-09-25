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
const now = "2026-09-07T08:00:00Z";

const user = { id: 7, email: "v2-browser@example.test", displayName: "V2 Browser QA", status: "ACTIVE" };
const conversation = {
  id: 101,
  userId: 7,
  title: "V2 多模态验收",
  lastMessageAt: now,
  createdAt: now,
  updatedAt: now,
};
const project = {
  id: 1,
  userId: 7,
  name: "V2 Intelligence Project",
  description: "Deterministic V2 browser acceptance project",
  conversationIds: [],
  createdAt: now,
  updatedAt: now,
};
const knowledgeBase = {
  id: 1,
  userId: 7,
  name: "V2 全局知识库",
  description: "Synthetic browser fixture",
  scope: "GLOBAL",
  projectId: null,
  isDefault: true,
  fileCount: 0,
  readyFileCount: 0,
  pendingFileCount: 0,
  errorFileCount: 0,
  createdAt: now,
  updatedAt: now,
};

const citation = {
  citationId: 1,
  label: "[1]",
  documentId: "v2-visual-evidence-1",
  source: "v2-architecture.png",
  score: 0.96,
  documentType: "image/png",
  chunkIndex: null,
  start: null,
  end: null,
  pageNumber: 1,
  assetId: "asset-v2-architecture",
  modality: "image",
  visualType: "architecture",
};

const task = {
  id: 501,
  userId: 7,
  conversationId: 101,
  requestId: "v2-browser-run-501",
  taskText: "结合正文和图表解释 Worker 与 Dispatcher 的关系",
  scheduler: "adaptive",
  planner: "multi_objective",
  executionMode: "auto",
  synthesisMode: "auto",
  deliveryMode: "direct",
  constraints: { maxLatencyMs: 30000, maxCost: 1, minQuality: 0.8 },
  status: "COMPLETED",
  resultText: "Dispatcher 负责调度 Worker，视觉证据显示 Worker Pool 通过队列接收任务。[1]",
  selectedAgents: ["multimodal-rag-agent"],
  latencyMs: 1280,
  estimatedCost: 0.0042,
  errorMessage: null,
  createdAt: now,
  updatedAt: now,
};

const runResult = {
  task,
  status: "COMPLETED",
  answer: task.resultText,
  citations: [citation],
  scheduler: "adaptive",
  planner: "multi_objective",
  executionMode: "auto",
  synthesisMode: "auto",
  taskProfile: { retrievalMode: "hybrid", needsVisualEvidence: true },
  selectedAgents: ["multimodal-rag-agent"],
  estimatedCost: 0.0042,
  elapsedMs: 1280,
  trace: [
    {
      kind: "rag",
      title: "Agentic RAG Completed",
      status: "completed",
      detail: JSON.stringify({ rounds: 1, stoppedReason: "grounded evidence selected" }),
      elapsedMs: 260,
    },
    {
      kind: "rag",
      title: "RAG Retrieval Completed",
      status: "completed",
      detail: JSON.stringify({
        retrievalMode: "hybrid",
        rawHits: 6,
        hits: 2,
        contextHits: 2,
        textCandidates: 2,
        visualCandidates: 4,
        documents: [
          {
            id: citation.documentId,
            source: citation.source,
            score: citation.score,
            modality: citation.modality,
            pageNumber: citation.pageNumber,
            visualType: citation.visualType,
            assetId: citation.assetId,
          },
          {
            id: "v2-text-evidence-1",
            source: "v2-architecture.md",
            score: 0.88,
            modality: "text",
            pageNumber: null,
            visualType: null,
            assetId: null,
          },
        ],
      }),
      elapsedMs: 140,
    },
    {
      kind: "rag",
      title: "RAG Grounding Guard",
      status: "completed",
      detail: JSON.stringify({ policy: "fail-closed", sufficient: true }),
      elapsedMs: 12,
    },
    {
      kind: "rag",
      title: "Citation Provenance Projected",
      status: "completed",
      detail: JSON.stringify({ usedCount: 1, availableCount: 2 }),
      elapsedMs: 8,
    },
    {
      kind: "routing",
      title: "Query Intelligence V2",
      status: "completed",
      detail: JSON.stringify({ retrievalMode: "HYBRID", reason: "text + visual relation query" }),
      elapsedMs: 5,
    },
  ],
  dag: {
    nodes: [{ id: "rag", label: "Multimodal RAG", kind: "agent", status: "COMPLETED" }],
    edges: [],
  },
  agentFeedback: [
    {
      agentId: 1,
      capability: "multimodal_rag",
      success: true,
      latencyMs: 1280,
      cost: 0.0042,
      qualityScore: 0.98,
      errorType: "",
    },
  ],
  observability: {
    modelCalls: 1,
    modelProvider: "mock",
    modelName: "mock-v2-vision",
    modelInputTokens: 320,
    modelOutputTokens: 96,
    modelTotalTokens: 416,
    modelLatencyMs: 620,
    toolCalls: 0,
    mcpEvents: 0,
    agentAttempts: 1,
    agentSuccesses: 1,
    agentFailures: 0,
    reschedules: 0,
    dagCompletedNodes: 1,
    dagSkippedNodes: 0,
    qualityEvaluations: 1,
    averageQuality: 0.98,
    modelEstimatedCost: 0.0042,
    modelCostKnown: true,
    toolSuccesses: 0,
    toolFailures: 0,
    retrievalMode: "hybrid",
    ragLatencyMs: 420,
    ragRawHits: 6,
    ragHits: 2,
    ragContextHits: 2,
    ragTextCandidates: 2,
    ragVisualCandidates: 4,
  },
  scorecard: {
    evaluator: "deterministic-mock-judge",
    status: "pass",
    overallScore: 0.98,
    taskSuccess: 1,
    answerQuality: 0.98,
    groundedness: 1,
    correctness: 0.98,
    citationQuality: 0.96,
    taskCompletion: 1,
    toolReliability: 1,
    ragQuality: 0.97,
    memoryContribution: 0,
    budgetCompliance: 1,
    latencyMs: 1280,
    estimatedCost: 0.0042,
    modelEstimatedCost: 0.0042,
    modelTokens: 416,
    failureCategory: "NONE",
    judgeReason: "回答与合成视觉证据一致，引用来自当前 Run 的已选证据。",
    violations: [],
    signals: { retrievalMode: "HYBRID" },
  },
};

const state = {
  knowledgeFiles: [],
  messages: [],
  tasks: [],
};

function envelope(data) {
  return JSON.stringify({ code: 0, message: "ok", data });
}

function errorEnvelope(status, message) {
  return JSON.stringify({ code: status, message });
}

function contentType(filename) {
  if (filename.endsWith(".html")) return "text/html; charset=utf-8";
  if (filename.endsWith(".js")) return "text/javascript; charset=utf-8";
  if (filename.endsWith(".css")) return "text/css; charset=utf-8";
  if (filename.endsWith(".svg")) return "image/svg+xml";
  return "application/octet-stream";
}

async function drain(req) {
  for await (const _chunk of req) {
    // The deterministic server only needs to prove the browser sent a body.
  }
}

function createServer() {
  return http.createServer(async (req, res) => {
    try {
      const requestUrl = new URL(req.url ?? "/", `http://${host}`);
      const key = `${req.method ?? "GET"} ${requestUrl.pathname}`;

      const fixed = new Map([
        ["GET /api/me", user],
        ["GET /api/conversations", [conversation]],
        ["GET /api/projects", [project]],
        ["GET /api/agents", []],
        ["GET /api/runtime/plugins", []],
        ["GET /api/tools", []],
        ["GET /api/mcp-servers", []],
        ["GET /api/knowledge/bases", [knowledgeBase]],
        ["GET /api/runtime/reliability", {
          enabled: true,
          queueDepth: 0,
          leased: 0,
          accepted: 1,
          failed: 0,
          canceled: 0,
          workers: 1,
          availableWorkers: 1,
          drainingWorkers: 0,
          circuitOpenWorkers: 0,
          oldestQueuedMs: 0,
        }],
        ["GET /api/organizations", []],
      ]);

      if (fixed.has(key)) {
        res.writeHead(200, { "content-type": "application/json" });
        res.end(envelope(fixed.get(key)));
        return;
      }

      if (key === "GET /api/conversations/101/messages") {
        res.writeHead(200, { "content-type": "application/json" });
        res.end(envelope(state.messages));
        return;
      }

      if (key === "GET /api/tasks") {
        res.writeHead(200, { "content-type": "application/json" });
        res.end(envelope(state.tasks));
        return;
      }

      if (key === "GET /api/knowledge/files") {
        res.writeHead(200, { "content-type": "application/json" });
        res.end(envelope(state.knowledgeFiles));
        return;
      }

      if (key === "GET /api/knowledge/bases/1/files") {
        res.writeHead(200, { "content-type": "application/json" });
        res.end(envelope(state.knowledgeFiles));
        return;
      }

      if (key === "POST /api/knowledge/bases/1/files") {
        await drain(req);
        const file = {
          id: 901,
          knowledgeBaseId: 1,
          knowledgeBaseName: knowledgeBase.name,
          scope: "GLOBAL",
          projectId: null,
          userId: 7,
          originalName: "v2-architecture.png",
          mediaType: "image/png",
          extension: "png",
          sizeBytes: 67,
          checksumSha256: "synthetic-v2-browser-sha256",
          storageKey: "synthetic/v2-architecture.png",
          status: "READY",
          chunkCount: 3,
          textChunkCount: 1,
          visualEvidenceCount: 2,
          pageCount: 1,
          visualStatus: "completed",
          visualErrorMessage: null,
          errorMessage: null,
          indexedAt: now,
          createdAt: now,
          updatedAt: now,
        };
        state.knowledgeFiles = [file];
        knowledgeBase.fileCount = 1;
        knowledgeBase.readyFileCount = 1;
        res.writeHead(200, { "content-type": "application/json" });
        res.end(envelope(file));
        return;
      }

      if (key === "POST /api/tasks/run-stream") {
        await drain(req);
        state.tasks = [task];
        state.messages = [
          {
            id: 1001,
            conversationId: 101,
            role: "user",
            content: task.taskText,
            status: "COMPLETED",
            requestId: task.requestId,
            metadata: {},
            createdAt: now,
          },
          {
            id: 1002,
            conversationId: 101,
            role: "assistant",
            content: runResult.answer,
            status: "COMPLETED",
            requestId: task.requestId,
            metadata: { citations: [citation] },
            createdAt: now,
          },
        ];
        res.writeHead(200, { "content-type": "application/x-ndjson; charset=utf-8", "cache-control": "no-store" });
        res.write(`${JSON.stringify({ type: "status", message: "正在执行多模态检索…" })}\n`);
        res.write(`${JSON.stringify({ type: "delta", delta: "Dispatcher 负责调度 Worker" })}\n`);
        res.end(`${JSON.stringify({ type: "result", result: runResult })}\n`);
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
  const configured = process.env.V2_BROWSER_BIN || process.env.BROWSER_E2E_BIN;
  const env = configured ? [configured] : [];
  if (process.platform === "win32") {
    return [
      ...env,
      "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
      "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
      "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
      "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
    ];
  }
  return [...env, "/usr/bin/chromium", "/usr/bin/google-chrome", "/usr/bin/chromium-browser"];
}

function resolveBrowser() {
  for (const candidate of browserCandidates()) {
    if (candidate && fs.existsSync(candidate)) return candidate;
  }
  throw new Error("No Chrome/Chromium/Edge binary found. Set V2_BROWSER_BIN explicitly.");
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
  try { child.kill(); } catch {}
  if (await waitForChildExit(child, 3000)) return;
  if (process.platform === "win32" && child.pid) {
    await new Promise((resolve) => {
      const killer = spawn("taskkill", ["/PID", String(child.pid), "/T", "/F"], { stdio: "ignore" });
      killer.once("error", resolve);
      killer.once("exit", resolve);
    });
    await waitForChildExit(child, 3000);
    return;
  }
  try { child.kill("SIGKILL"); } catch {}
  await waitForChildExit(child, 3000);
}

async function closeBrowser(child, cdp) {
  if (cdp) {
    try { await cdp.send("Browser.close"); } catch {}
    try { cdp.close(); } catch {}
  }
  if (!(await waitForChildExit(child, 5000))) await forceKillBrowserTree(child);
}

async function closeServer(server) {
  if (!server.listening) return;
  await new Promise((resolve) => server.close(resolve));
}

async function removeProfileWithRetry(profile, attempts = 20, delayMs = 150) {
  let lastError;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      fs.rmSync(profile, { recursive: true, force: true, maxRetries: 0 });
      return;
    } catch (error) {
      lastError = error;
      if (!error || !["EBUSY", "EPERM", "ENOTEMPTY"].includes(error.code) || attempt === attempts) throw error;
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
    await sleep(100);
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
    } catch {}
    await sleep(100);
  }
  throw new Error("Timed out waiting for browser page target");
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
    const result = await this.send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.text ?? "Runtime.evaluate failed");
    return result.result.value;
  }
  close() { this.ws.close(); }
}

async function waitFor(cdp, predicateExpression, label, timeoutMs = 12000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await cdp.evaluate(`Boolean(${predicateExpression})`)) return;
    await sleep(100);
  }
  const body = await cdp.evaluate("document.body.innerText");
  throw new Error(`Timed out waiting for ${label}. Body was:\n${body}`);
}

function clickButtonExpression(label) {
  return `(() => { const target = [...document.querySelectorAll('button')].find((node) => node.textContent?.trim().includes(${JSON.stringify(label)})); if (!target) return false; target.click(); return true; })()`;
}

async function clickButton(cdp, label) {
  assert.equal(await cdp.evaluate(clickButtonExpression(label)), true, `button ${label} should exist`);
}

async function run() {
  assert.ok(fs.existsSync(path.join(dist, "index.html")), "dist/index.html missing; run npm run build first");
  const serverPort = await freePort();
  const debugPort = await freePort();
  const server = createServer();
  await new Promise((resolve) => server.listen(serverPort, host, resolve));
  const appUrl = `http://${host}:${serverPort}`;
  const profile = fs.mkdtempSync(path.join(process.cwd(), ".v2-browser-"));
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
  try {
    const page = await waitForPageTarget(debugPort);
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
      `document.querySelector('.app-shell') && document.querySelector('.user-card strong')?.textContent?.trim() === "V2 Browser QA"`,
      "authenticated V2 shell",
    );

    // 1. Upload a deterministic synthetic image through the real React upload UI.
    await clickButton(cdp, "知识库");
    await waitFor(cdp, `document.querySelector('main h1')?.textContent?.includes("知识库")`, "Knowledge Center");
    await clickButton(cdp, "上传知识");
    await waitFor(cdp, `document.querySelector('input[type=file]')`, "knowledge file input");
    const injected = await cdp.evaluate(`(() => {
      const input = document.querySelector('input[type=file]');
      if (!input) return false;
      const bytes = new Uint8Array([137,80,78,71,13,10,26,10,0,0,0,13,73,72,68,82]);
      const file = new File([bytes], 'v2-architecture.png', { type: 'image/png', lastModified: Date.now() });
      const transfer = new DataTransfer();
      transfer.items.add(file);
      input.files = transfer.files;
      input.dispatchEvent(new Event('change', { bubbles: true }));
      return input.files?.length === 1;
    })()`);
    assert.equal(injected, true, "synthetic V2 image should be attached");
    await waitFor(cdp, `document.body.innerText.includes("已选择 1 个文件")`, "staged synthetic image");
    await clickButton(cdp, "开始上传");
    await waitFor(cdp, `document.body.innerText.includes("v2-architecture.png")`, "uploaded knowledge filename");
    await waitFor(cdp, `(() => { const summary = document.querySelector(".knowledge-v2-evidence-summary")?.textContent ?? ""; return summary.includes("图片 2 张") && summary.includes("视觉完成"); })()`, "visual evidence ingestion state");

    // 2. Execute a deterministic HYBRID task through the real Workspace flow.
    await clickButton(cdp, "工作台");
    await waitFor(
      cdp,
      `document.querySelector('.workspace-core') && document.querySelector('.workspace-breadcrumb span')?.textContent?.includes("工作台")`,
      "workspace",
    );
    const prompt = task.taskText;
    const populated = await cdp.evaluate(`(() => {
      const textarea = document.querySelector('.composer textarea');
      if (!textarea) return false;
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set;
      setter?.call(textarea, ${JSON.stringify(task.taskText)});
      textarea.dispatchEvent(new Event('input', { bubbles: true }));
      textarea.dispatchEvent(new Event('change', { bubbles: true }));
      return textarea.value === ${JSON.stringify(task.taskText)};
    })()`);
    assert.equal(populated, true, "workspace prompt should be populated");
    await clickButton(cdp, "运行任务");
    await waitFor(cdp, `document.body.innerText.includes("Dispatcher 负责调度 Worker")`, "multimodal final answer", 15000);
    await waitFor(
      cdp,
      `document.querySelector('button.citation-source-summary') && document.querySelector('button.citation-source-summary')?.textContent?.includes("[1]")`,
      "multimodal citation source summary",
    );
    assert.equal(await cdp.evaluate(`document.body.innerText.includes(${JSON.stringify(prompt)})`), true);

    // 3. Citation provenance must expose page + modality information through the current Sources disclosure UI.
    assert.equal(
      await cdp.evaluate(`(() => { const el = document.querySelector('button.citation-source-summary'); if (!el) return false; el.click(); return true; })()`),
      true,
      "citation source summary should be clickable",
    );
    await waitFor(
      cdp,
      `document.querySelector('.citation-source-details') && document.body.innerText.includes("v2-architecture.png") && document.body.innerText.includes("Page 1") && document.body.innerText.includes("architecture")`,
      "citation provenance",
    );

    // 4. Run Details must expose multimodal RAG, evaluation and usage/cost.
    await clickButton(cdp, "运行详情");
    await waitFor(cdp, `document.querySelector('[aria-label="运行详情"]')`, "Run Details drawer");
    await waitFor(cdp, `(() => { const text = document.body.innerText.toUpperCase(); return text.includes("RETRIEVAL MODE") && text.includes("HYBRID"); })()`, "overview retrieval mode");
    await waitFor(cdp, `(() => { const text = document.body.innerText.toUpperCase(); return text.includes("MODEL COST") && text.includes("MOCK-V2-VISION") && text.includes("$0.0042"); })()`, "usage and cost telemetry");

    await clickButton(cdp, "知识检索");
    await waitFor(cdp, `(() => { const text = document.body.innerText.toUpperCase(); return text.includes("已选多模态证据") && text.includes("V2-ARCHITECTURE.PNG") && text.includes("第 1 页") && text.includes("ARCHITECTURE"); })()`, "multimodal RAG trace");

    await clickButton(cdp, "质量评估");
    await waitFor(cdp, `document.body.innerText.includes("正确性") && document.body.innerText.includes("引用质量") && document.body.innerText.includes("评测说明")`, "advanced evaluation scorecard");

    console.log("V2 Deterministic Multimodal Browser E2E: PASS");
  } catch (error) {
    primaryError = error;
  } finally {
    try { await closeBrowser(child, cdp); } catch (error) { cleanupError ??= error; }
    try { await closeServer(server); } catch (error) { cleanupError ??= error; }
    try { await removeProfileWithRetry(profile); } catch (error) { cleanupError ??= error; }
  }

  if (primaryError) {
    if (cleanupError) console.error(`V2 browser cleanup warning: ${cleanupError.stack ?? cleanupError}`);
    throw primaryError;
  }
  if (cleanupError) throw cleanupError;
}

await run();
