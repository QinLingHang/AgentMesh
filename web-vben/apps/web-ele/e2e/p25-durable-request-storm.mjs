/* oxlint-disable no-console -- P25 evidence runner requires stdout diagnostics. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import process from 'node:process';

import { chromium } from 'playwright';

const baseUrl = process.env.P25_QA_WEB_URL || 'http://127.0.0.1:5777';
const email = process.env.P25_QA_EMAIL;
const password = process.env.P25_QA_PASSWORD;
if (!email || !password)
  throw new Error('P25_QA_EMAIL and P25_QA_PASSWORD are required');
const browserPath = [
  process.env.BROWSER_E2E_BIN,
  String.raw`C:\Program Files\Google\Chrome\Application\chrome.exe`,
  String.raw`C:\Program Files\Microsoft\Edge\Application\msedge.exe`,
]
  .filter(Boolean)
  .find((candidate) => fs.existsSync(candidate));
if (!browserPath) throw new Error('Chrome/Edge not found; set BROWSER_E2E_BIN');

const browser = await chromium.launch({
  executablePath: browserPath,
  headless: true,
});
const page = await browser.newPage();
const submitRequests = new Map();
const submitEvidence = [];
const submitPath = '/api/tasks/submit-stream';
const safeSubmitTaxonomy = (value) => {
  const text = String(value || '').toUpperCase();
  return (
    [
      'MODEL_BAD_REQUEST',
      'MODEL_AUTH',
      'MODEL_TIMEOUT',
      'MODEL_RATE_LIMIT',
      'MODEL_UNAVAILABLE',
    ].find((category) => text.includes(category)) || ''
  );
};
const safeRequestFailure = (value) => {
  const text = String(value || '').toUpperCase();
  const known = text.match(
    /(?:NET::)?ERR_[A-Z0-9_]+|NS_BINDING_ABORTED|REQUEST_ABORTED/,
  );
  return known?.[0] || 'REQUEST_FAILED';
};
const submitUrlPath = (raw) => {
  try {
    return new URL(raw).pathname;
  } catch {
    return '';
  }
};
const pushSubmitTimeline = async (phase, details) => {
  await page
    .evaluate(
      ({ phase: safePhase, details: safeDetails }) => {
        window.__p25Timeline?.push({
          at: performance.now(),
          phase: safePhase,
          ...safeDetails,
        });
      },
      { phase, details },
    )
    .catch(() => {});
};
const inspectSubmitPayload = (body, contentType) => {
  const result = {
    bodyLength: body.length,
    responseCode: null,
    errorTaxonomy: '',
    taskId: 0,
  };
  const objects = [];
  const text = body.toString('utf8');
  try {
    if (/application\/(?:[^;]+\+)?json\b/i.test(contentType))
      objects.push(JSON.parse(text));
    else if (/application\/(?:x-)?ndjson\b/i.test(contentType)) {
      for (const line of text.split(/\r?\n/)) {
        if (!line.trim()) continue;
        try {
          objects.push(JSON.parse(line));
        } catch {
          /* only valid JSON lines are inspected */
        }
      }
    }
  } catch {
    /* malformed payload is represented only by status/type/length */
  }
  for (const item of objects) {
    if (!item || typeof item !== 'object') continue;
    result.responseCode ??=
      item.code ?? item.errorCode ?? item.error?.code ?? null;
    result.errorTaxonomy ||= safeSubmitTaxonomy(
      item.errorCode || item.error?.code || item.message,
    );
    result.taskId ||= Number(
      item.taskId ||
        item.data?.taskId ||
        item.data?.task?.id ||
        item.result?.taskId ||
        item.result?.task?.id ||
        item.data?.result?.task?.id ||
        0,
    );
  }
  return result;
};
const submitForConversation = (conversationId) =>
  submitEvidence.findLast((item) => item.conversationId === conversationId);
const submitSummary = (conversationId) => {
  const item = submitForConversation(conversationId);
  return {
    submitRequestCount: submitEvidence.filter(
      (entry) => entry.conversationId === conversationId,
    ).length,
    submitResponseObserved: Boolean(item?.responseObserved),
    submitHttpStatus: item?.httpStatus ?? null,
    submitContentType: item?.contentType || '',
    submitResponseFinished: Boolean(item?.responseFinished),
    submitRequestFailed: Boolean(item?.requestFailed),
    submitFailureTextSafe: item?.failureTextSafe || '',
    submitResponseCode: item?.responseCode ?? null,
    submitResponseErrorTaxonomy: item?.errorTaxonomy || '',
    submitReturnedTaskId: item?.taskId || 0,
    submitResponseDurationMs: item?.durationMs ?? null,
    submitResponseBodyLength: item?.bodyLength ?? null,
  };
};
page.on('request', (request) => {
  if (
    request.method() !== 'POST' ||
    submitUrlPath(request.url()) !== submitPath
  )
    return;
  let conversationId = 0;
  try {
    conversationId = Number(request.postDataJSON()?.conversationId || 0);
  } catch {}
  const evidence = {
    conversationId,
    startedAt: Date.now(),
    responseObserved: false,
    httpStatus: null,
    contentType: '',
    responseFinished: false,
    requestFailed: false,
    failureTextSafe: '',
    responseCode: null,
    errorTaxonomy: '',
    taskId: 0,
    durationMs: null,
    bodyLength: null,
  };
  submitRequests.set(request, evidence);
  submitEvidence.push(evidence);
  void pushSubmitTimeline('submit-request-start', { conversationId });
});
page.on('response', (response) => {
  const evidence = submitRequests.get(response.request());
  if (!evidence) return;
  evidence.responseObserved = true;
  evidence.httpStatus = response.status();
  evidence.contentType = response.headers()['content-type'] || '';
  void pushSubmitTimeline('submit-response', {
    conversationId: evidence.conversationId,
    status: evidence.httpStatus,
    contentType: evidence.contentType,
  });
});
page.on('requestfinished', async (request) => {
  const evidence = submitRequests.get(request);
  if (!evidence) return;
  evidence.responseFinished = true;
  evidence.durationMs = Date.now() - evidence.startedAt;
  try {
    const response = await request.response();
    if (response) {
      const inspected = inspectSubmitPayload(
        await response.body(),
        evidence.contentType,
      );
      evidence.responseCode = inspected.responseCode;
      evidence.errorTaxonomy = inspected.errorTaxonomy;
      evidence.taskId = inspected.taskId;
      evidence.bodyLength = inspected.bodyLength;
      if (evidence.taskId > 0) {
        await page
          .evaluate((taskId) => {
            if (!window.__p25State) return;
            window.__p25State.submitReturnedTaskId = taskId;
            if (!window.__p25State.originalTaskId)
              window.__p25State.originalTaskId = taskId;
          }, evidence.taskId)
          .catch(() => {});
      }
    }
  } catch {
    /* lifecycle evidence remains valid even when body is unavailable */
  }
  await pushSubmitTimeline('submit-request-finished', {
    conversationId: evidence.conversationId,
    taskId: evidence.taskId,
    durationMs: evidence.durationMs,
  });
});
page.on('requestfailed', (request) => {
  const evidence = submitRequests.get(request);
  if (!evidence) return;
  evidence.requestFailed = true;
  evidence.failureTextSafe = safeRequestFailure(request.failure()?.errorText);
  evidence.durationMs = Date.now() - evidence.startedAt;
  void pushSubmitTimeline('submit-request-failed', {
    conversationId: evidence.conversationId,
    failure: evidence.failureTextSafe,
    durationMs: evidence.durationMs,
  });
});
const requireUniqueVisible = async (selector, label) => {
  const locator = page.locator(selector);
  try {
    await locator.first().waitFor({ state: 'visible', timeout: 5000 });
    const count = await locator.count();
    assert.equal(count, 1, `${label} selector matched ${count} elements`);
    console.log(`[P25 browser] ${label} selector found`);
    return locator.first();
  } catch (error) {
    throw new Error(
      `${label} locator failure at ${page.url()}: ${error.message}`,
      { cause: error },
    );
  }
};
const waitForFirstSSE = async (scenario, conversationId) => {
  try {
    await page.waitForFunction(
      () =>
        window.__p25Timeline.some(
          (item) => item.phase === 'first-sse-connected',
        ),
      null,
      { timeout: 20_000 },
    );
  } catch {
    await page.waitForTimeout(250);
    const state = await page.evaluate(() => window.__p25State || {});
    const evidence = {
      scenario,
      newConversationId: conversationId,
      ...submitSummary(conversationId),
      eventsObservedTaskId: Number(state.eventsObservedTaskId || 0),
    };
    console.error(`[P25 browser] ${scenario} submit evidence`);
    console.error(JSON.stringify(evidence, null, 2));
    if (evidence.submitRequestFailed) {
      throw new Error(
        `${scenario}_REQUEST_FAILED reason=${evidence.submitFailureTextSafe || 'REQUEST_FAILED'}`,
      );
    }
    if (
      evidence.submitResponseObserved &&
      Number(evidence.submitHttpStatus) >= 400
    ) {
      throw new Error(
        `${scenario}_SUBMIT_HTTP_ERROR status=${evidence.submitHttpStatus} taxonomy=${evidence.submitResponseErrorTaxonomy || 'HTTP_ERROR'}`,
      );
    }
    if (
      evidence.submitResponseFinished &&
      Number(evidence.submitHttpStatus) >= 200 &&
      Number(evidence.submitHttpStatus) < 300 &&
      !evidence.submitReturnedTaskId
    ) {
      throw new Error(`${scenario}_SUBMIT_2XX_WITHOUT_TASK_ID`);
    }
    if (evidence.submitReturnedTaskId) {
      throw new Error(
        `${scenario}_SUBMIT_SUCCESS_SSE_NOT_ESTABLISHED taskId=${evidence.submitReturnedTaskId}`,
      );
    }
    throw new Error(`${scenario}_SUBMIT_RESPONSE_TIMEOUT`);
  }
};
try {
  await page.addInitScript(() => {
    const originalFetch = window.fetch.bind(window);
    window.__p25Timeline = [];
    const scenarioMode = sessionStorage.getItem('p25ScenarioMode') || 'A';
    window.__p25State = {
      abortRequested: false,
      assistantText: '',
      deltaOrdinals: [],
      duplicateCount: 0,
      eventTaskIds: [],
      eventCursors: [],
      executionIds: [],
      fences: [],
      terminalStatus: '',
      originalTaskId: 0,
      newConversationId: 0,
      submittedConversationIds: [],
      taskErrorTaxonomy: '',
      reconnected: false,
      reconnectBlocked: false,
      scenarioMode,
      firstFallbackStatus: '',
      submitReturnedTaskId: 0,
      eventsObservedTaskId: 0,
    };
    const state = window.__p25State;
    const seenStreamIds = new Set();
    const record = (phase, details = {}) => {
      const item = { at: performance.now(), phase, ...details };
      window.__p25Timeline.push(item);
      return item;
    };
    const safePath = (raw) => {
      try {
        return new URL(raw, location.href).pathname;
      } catch {
        return String(raw).split('?')[0];
      }
    };
    const qaConversationTitle = `P25 QA ${scenarioMode} ${new Date().toISOString()}`;
    const terminalStatuses = new Set([
      'AUTH_REQUIRED',
      'CANCELED',
      'COMPLETED',
      'ERROR',
      'FAILED',
      'INPUT_REQUIRED',
    ]);
    const safeErrorTaxonomy = (value) => {
      const text = String(value || '').toUpperCase();
      return (
        [
          'MODEL_BAD_REQUEST',
          'MODEL_AUTH',
          'MODEL_TIMEOUT',
          'MODEL_RATE_LIMIT',
          'MODEL_UNAVAILABLE',
        ].find((category) => text.includes(category)) || 'MODEL_ERROR_OTHER'
      );
    };
    const captureTerminal = (payload, source) => {
      if (!payload || !terminalStatuses.has(payload.status)) return;
      state.terminalStatus = payload.status;
      if (payload.status === 'ERROR' || payload.status === 'FAILED') {
        state.taskErrorTaxonomy = safeErrorTaxonomy(
          payload.errorCategory || payload.errorCode || payload.errorMessage,
        );
      }
      record('terminal-status', {
        status: payload.status,
        source,
        errorTaxonomy: state.taskErrorTaxonomy || undefined,
      });
      if (!state.abortRequested)
        record('scenario-task-completed-before-disconnect', {
          status: payload.status,
        });
    };
    const eventRequest = (url, init) => {
      const headers = new Headers(
        init.headers || (url instanceof Request ? url.headers : undefined),
      );
      const path = safePath(url instanceof Request ? url.url : url);
      const match = path.match(/\/api\/tasks\/(\d+)\/events$/);
      return {
        path,
        taskId: match ? Number(match[1]) : 0,
        cursor: headers.get('Last-Event-ID') || '0',
      };
    };
    const combineSignals = (productionSignal, qaSignal) => {
      const signals = [productionSignal, qaSignal].filter(Boolean);
      if (AbortSignal.any) return AbortSignal.any(signals);
      const combined = new AbortController();
      for (const signal of signals) {
        if (signal.aborted) combined.abort(signal.reason);
        else
          signal.addEventListener(
            'abort',
            () => combined.abort(signal.reason),
            { once: true },
          );
      }
      return combined.signal;
    };
    let firstEventsAt = 0;
    let disconnectUntil = 0;
    let firstAbortController;
    let abortTimer;
    let sseBuffer = '';
    let requestSequence = 0;
    const requestAbort = (reason) => {
      if (state.abortRequested || state.terminalStatus) return;
      state.abortRequested = true;
      state.reconnectBlocked = true;
      disconnectUntil =
        state.scenarioMode === 'A' ? performance.now() + 12_000 : 0;
      record('forced-sse-abort', {
        reason,
        disconnectUntil,
        cursor: state.eventCursors.at(-1) || '0',
      });
      firstAbortController.abort('P25 QA controlled SSE disconnect');
      if (state.scenarioMode === 'A') {
        setTimeout(() => {
          state.reconnectBlocked = false;
          record('fixed-outage-ended');
        }, 12_000);
      }
    };
    const observeFrame = (frame) => {
      let id = '';
      let kind = '';
      let data = '';
      for (const line of frame.split('\n')) {
        if (line.startsWith('id:')) id = line.slice(3).trim();
        if (line.startsWith('event:')) kind = line.slice(6).trim();
        if (line.startsWith('data:')) data += line.slice(5).trimStart();
      }
      if (!kind || !data) return;
      let payload;
      try {
        payload = JSON.parse(data);
      } catch {
        return;
      }
      if (id) {
        state.eventCursors.push(id);
        record('sse-frame', { kind, cursor: id });
      }
      if (payload.taskId) state.eventTaskIds.push(Number(payload.taskId));
      if (kind === 'stream_reset') state.assistantText = '';
      if (kind === 'delta') {
        if (seenStreamIds.has(payload.streamId)) state.duplicateCount += 1;
        else seenStreamIds.add(payload.streamId);
        state.deltaOrdinals.push(Number(payload.ordinal));
        state.executionIds.push(String(payload.executionId || ''));
        state.fences.push(Number(payload.fenceEpoch));
        state.assistantText += String(payload.delta || '');
        record('delta-frame', {
          cursor: id,
          taskId: Number(payload.taskId),
          ordinal: Number(payload.ordinal),
          executionId: String(payload.executionId || ''),
          fenceEpoch: Number(payload.fenceEpoch),
        });
        if (state.deltaOrdinals.length >= 2) {
          clearTimeout(abortTimer);
          setTimeout(() => requestAbort('two-deltas-observed'), 100);
        }
      }
      if (
        kind === 'task' &&
        [
          'AUTH_REQUIRED',
          'CANCELED',
          'COMPLETED',
          'ERROR',
          'FAILED',
          'INPUT_REQUIRED',
        ].includes(payload.status)
      ) {
        captureTerminal(payload, 'sse');
      }
    };
    window.fetch = async (input, init = {}) => {
      const rawUrl = input instanceof Request ? input.url : String(input);
      const path = safePath(rawUrl);
      const requestSeq = ++requestSequence;
      const method = String(
        init.method || (input instanceof Request ? input.method : 'GET'),
      ).toUpperCase();
      let effectiveInit = init;
      if (
        path === '/api/conversations' &&
        method === 'POST' &&
        typeof init.body === 'string'
      ) {
        const body = JSON.parse(init.body);
        effectiveInit = {
          ...init,
          body: JSON.stringify({ ...body, title: qaConversationTitle }),
        };
        record('qa-conversation-create-request', {
          title: qaConversationTitle,
        });
      }
      if (path === '/api/tasks/submit-stream') {
        let conversationId = 0;
        try {
          conversationId = Number(
            JSON.parse(String(init.body || '{}')).conversationId || 0,
          );
        } catch {}
        state.submittedConversationIds.push(conversationId);
        record('durable-submit', { path, conversationId });
      }
      const isAuthoritativeRefresh =
        path === '/api/tasks' ||
        path === '/api/conversations' ||
        /^\/api\/conversations\/\d+\/messages(?:\/page)?$/.test(path);
      if (isAuthoritativeRefresh && state.terminalStatus)
        record('terminal-refresh', { path, requestSeq });
      const wasFallbackPoll =
        path === '/api/tasks' &&
        !state.terminalStatus &&
        state.abortRequested &&
        !state.reconnected;
      if (wasFallbackPoll) record('fallback-poll', { path, requestSeq });
      record('request', { path, method, requestSeq });
      if (path.endsWith('/events')) {
        const metadata = eventRequest(input, effectiveInit);
        if (metadata.taskId) state.eventsObservedTaskId = metadata.taskId;
        if (!state.originalTaskId) state.originalTaskId = metadata.taskId;
        record('events-request-start', metadata);
        if (!firstEventsAt) {
          firstEventsAt = performance.now();
          firstAbortController = new AbortController();
          const signal = combineSignals(
            effectiveInit.signal,
            firstAbortController.signal,
          );
          const response = await originalFetch(input, {
            ...effectiveInit,
            signal,
          });
          record('first-sse-connected', {
            status: response.status,
            contentType: response.headers.get('content-type') || '',
          });
          if (state.scenarioMode === 'A') {
            abortTimer = setTimeout(
              () => requestAbort('connected-for-2500ms'),
              2500,
            );
          }
          if (!response.body) return response;
          const reader = response.body.getReader();
          const decoder = new TextDecoder();
          const observedBody = new ReadableStream({
            async start(controller) {
              try {
                while (true) {
                  const { done, value } = await reader.read();
                  if (done) {
                    record('first-sse-body-done');
                    controller.close();
                    return;
                  }
                  sseBuffer += decoder
                    .decode(value, { stream: true })
                    .replaceAll('\r\n', '\n');
                  let boundary = sseBuffer.indexOf('\n\n');
                  while (boundary !== -1) {
                    observeFrame(sseBuffer.slice(0, boundary));
                    sseBuffer = sseBuffer.slice(boundary + 2);
                    boundary = sseBuffer.indexOf('\n\n');
                  }
                  controller.enqueue(value);
                }
              } catch (error) {
                record('first-sse-body-error', {
                  name: error?.name || 'Error',
                });
                controller.error(error);
              }
            },
            cancel(reason) {
              record('first-sse-body-cancelled');
              return reader.cancel(reason);
            },
          });
          return new Response(observedBody, {
            status: response.status,
            statusText: response.statusText,
            headers: response.headers,
          });
        }
        if (state.reconnectBlocked) {
          record('reconnect-attempt-blocked', metadata);
          throw new TypeError('P25 QA controlled SSE disconnect');
        }
        const response = await originalFetch(input, effectiveInit);
        state.reconnected = true;
        record('second-sse-connected', {
          ...metadata,
          status: response.status,
          contentType: response.headers.get('content-type') || '',
        });
        if (!response.body) return response;
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        const observedBody = new ReadableStream({
          async start(controller) {
            try {
              while (true) {
                const { done, value } = await reader.read();
                if (done) {
                  record('second-sse-body-done');
                  controller.close();
                  return;
                }
                buffer += decoder
                  .decode(value, { stream: true })
                  .replaceAll('\r\n', '\n');
                let boundary = buffer.indexOf('\n\n');
                while (boundary !== -1) {
                  observeFrame(buffer.slice(0, boundary));
                  buffer = buffer.slice(boundary + 2);
                  boundary = buffer.indexOf('\n\n');
                }
                controller.enqueue(value);
              }
            } catch (error) {
              record('second-sse-body-error', { name: error?.name || 'Error' });
              controller.error(error);
            }
          },
          cancel(reason) {
            record('second-sse-body-cancelled');
            return reader.cancel(reason);
          },
        });
        return new Response(observedBody, {
          status: response.status,
          statusText: response.statusText,
          headers: response.headers,
        });
      }
      const response = await originalFetch(input, effectiveInit);
      if (path === '/api/conversations' && method === 'POST') {
        response
          .clone()
          .json()
          .then((created) => {
            state.newConversationId = Number(
              created?.data?.id || created?.id || 0,
            );
            record('qa-conversation-created', {
              conversationId: state.newConversationId,
              title: qaConversationTitle,
            });
          })
          .catch(() => record('qa-conversation-create-response-unavailable'));
      }
      if (path === '/api/tasks' && state.originalTaskId) {
        response
          .clone()
          .json()
          .then((payload) => {
            const findTask = (value) => {
              if (Array.isArray(value)) {
                for (const item of value) {
                  const found = findTask(item);
                  if (found) return found;
                }
                return null;
              }
              if (!value || typeof value !== 'object') return null;
              const candidateId = Number(value.id || value.taskId || 0);
              if (
                candidateId === state.originalTaskId &&
                typeof value.status === 'string'
              )
                return value;
              for (const item of Object.values(value)) {
                const found = findTask(item);
                if (found) return found;
              }
              return null;
            };
            const task = findTask(payload);
            if (!task) return;
            record('task-refresh-status', {
              taskId: state.originalTaskId,
              status: task.status,
            });
            if (wasFallbackPoll && !state.firstFallbackStatus) {
              state.firstFallbackStatus = task.status;
              record('first-fallback-result', {
                taskId: state.originalTaskId,
                status: task.status,
              });
              if (state.scenarioMode === 'B' && task.status === 'RUNNING') {
                state.reconnectBlocked = false;
                record('reconnect-block-released', {
                  reason: 'first-fallback-running',
                });
              }
            }
            if (task.status === 'ERROR' || task.status === 'FAILED') {
              state.taskErrorTaxonomy = safeErrorTaxonomy(
                task.errorCategory || task.errorCode || task.errorMessage,
              );
            }
            if (!state.terminalStatus) {
              captureTerminal(task, 'tasks-refresh');
              if (terminalStatuses.has(task.status)) {
                const authoritative = (requestPath) =>
                  requestPath === '/api/tasks' ||
                  requestPath === '/api/conversations' ||
                  /^\/api\/conversations\/\d+\/messages(?:\/page)?$/.test(
                    requestPath,
                  );
                for (const item of window.__p25Timeline) {
                  if (
                    item.requestSeq <= requestSeq ||
                    !authoritative(item.path)
                  )
                    continue;
                  if (item.phase === 'fallback-poll')
                    item.phase = 'terminal-refresh';
                  if (
                    item.phase === 'request' &&
                    !window.__p25Timeline.some(
                      (candidate) =>
                        candidate.phase === 'terminal-refresh' &&
                        candidate.requestSeq === item.requestSeq,
                    )
                  ) {
                    record('terminal-refresh', {
                      path: item.path,
                      requestSeq: item.requestSeq,
                    });
                  }
                }
              }
            }
          })
          .catch(() =>
            record('fallback-task-status-unavailable', {
              taskId: state.originalTaskId,
            }),
          );
      }
      return response;
    };
  });
  console.log(`[P25 browser] navigating to ${baseUrl}/agentmesh/login`);
  await page.goto(`${baseUrl}/agentmesh/login`, {
    waitUntil: 'domcontentloaded',
  });
  console.log(`[P25 browser] login page loaded; current URL=${page.url()}`);
  await page.evaluate(() =>
    window.__p25Timeline.push({
      at: performance.now(),
      phase: 'login-page-loaded',
    }),
  );
  const usernameInput = await requireUniqueVisible(
    'form.auth-form input[autocomplete="email"]',
    'username',
  );
  const passwordInput = await requireUniqueVisible(
    'form.auth-form input[autocomplete="current-password"]',
    'password',
  );
  const loginButton = await requireUniqueVisible(
    'form.auth-form > button.submit-button[type="submit"]',
    'login submit',
  );
  await usernameInput.fill(email);
  await passwordInput.fill(password);
  await loginButton.click();
  console.log('[P25 browser] login submit clicked');
  await page.waitForURL((url) => url.pathname === '/agentmesh/workspace', {
    timeout: 20_000,
  });
  console.log(`[P25 browser] post-login URL=${page.url()}`);
  await page.evaluate(() =>
    window.__p25Timeline.push(
      { at: performance.now(), phase: 'login-completed' },
      { at: performance.now(), phase: 'workspace-entered' },
    ),
  );

  const mediumPrompt =
    '请用 30 个编号短段解释 Durable Token Streaming。每段约 20-30 个汉字，逐段解释生产、控制面、lease、fence、Redis live buffer、SSE、cursor、replay、stream_reset 和客户端恢复。不要合并段落。';

  // Scenario A owns its conversation/task and measures only request-storm and
  // fallback behavior. Completion during the fixed outage is valid evidence;
  // this scenario intentionally makes no reconnect assertion.
  const scenarioANewTask = await requireUniqueVisible(
    '.new-task',
    'scenario A fresh conversation',
  );
  await scenarioANewTask.click();
  await page.waitForFunction(
    () => Number(window.__p25State.newConversationId) > 0,
    null,
    { timeout: 20_000 },
  );
  const scenarioAConversationId = await page.evaluate(
    () => window.__p25State.newConversationId,
  );
  await page
    .locator('.conversation-row.active')
    .filter({ hasText: 'P25 QA A' })
    .waitFor({ state: 'visible', timeout: 20_000 });
  const scenarioAPrompt = await requireUniqueVisible(
    '.composer-card textarea',
    'scenario A prompt',
  );
  const scenarioARun = await requireUniqueVisible(
    '.composer-toolbar .el-button--primary',
    'scenario A run',
  );
  await scenarioAPrompt.fill(process.env.P25_QA_PROMPT || mediumPrompt);
  await scenarioARun.click();
  await waitForFirstSSE('SCENARIO_A', scenarioAConversationId);
  await page.waitForFunction(
    () => window.__p25State.abortRequested || window.__p25State.terminalStatus,
    null,
    { timeout: 15_000 },
  );
  if (!(await page.evaluate(() => window.__p25State.abortRequested)))
    throw new Error('SCENARIO_TOO_FAST');
  await page.waitForFunction(
    () =>
      window.__p25Timeline.some((item) => item.phase === 'fixed-outage-ended'),
    null,
    { timeout: 15_000 },
  );
  await page.waitForTimeout(250);

  const scenarioA = await page.evaluate(() => ({
    timeline: window.__p25Timeline,
    state: window.__p25State,
  }));
  const scenarioAFirstConnected = scenarioA.timeline.find(
    (item) => item.phase === 'first-sse-connected',
  );
  const scenarioAAbort = scenarioA.timeline.find(
    (item) => item.phase === 'forced-sse-abort',
  );
  const scenarioAFallback = scenarioA.timeline
    .filter((item) => item.phase === 'fallback-poll')
    .map((item) => item.at);
  const scenarioAFallbackGaps = scenarioAFallback
    .slice(1)
    .map((at, index) => at - scenarioAFallback[index]);
  const scenarioAHealthyPolling = scenarioA.timeline.filter(
    (item) =>
      item.phase === 'request' &&
      scenarioAFirstConnected &&
      scenarioAAbort &&
      item.at > scenarioAFirstConnected.at &&
      item.at < scenarioAAbort.at &&
      (item.path === '/api/tasks' ||
        item.path === '/api/conversations' ||
        /^\/api\/conversations\/\d+\/messages(?:\/page)?$/.test(item.path)),
  );
  const scenarioATerminalRefresh = scenarioA.timeline.filter(
    (item) => item.phase === 'terminal-refresh',
  );
  const scenarioARequests = scenarioA.timeline.filter(
    (item) => item.phase === 'request',
  );
  const scenarioAEvidence = {
    scenario: 'A-request-storm-fallback',
    newConversationId: scenarioAConversationId,
    taskId: scenarioA.state.originalTaskId,
    ...submitSummary(scenarioAConversationId),
    eventsObservedTaskId: scenarioA.state.eventsObservedTaskId || 0,
    submittedConversationIds: scenarioA.state.submittedConversationIds,
    tasksRequestCount: scenarioARequests.filter(
      (item) => item.path === '/api/tasks',
    ).length,
    conversationRequestCount: scenarioARequests.filter(
      (item) => item.path === '/api/conversations',
    ).length,
    messageRequestCount: scenarioARequests.filter((item) =>
      /^\/api\/conversations\/\d+\/messages(?:\/page)?$/.test(item.path),
    ).length,
    healthyPollingCount: scenarioAHealthyPolling.length,
    fallbackTimestampsMs: scenarioAFallback,
    fallbackGapsMs: scenarioAFallbackGaps,
    terminalStatus: scenarioA.state.terminalStatus,
    terminalRefreshCounts: {
      tasks: scenarioATerminalRefresh.filter(
        (item) => item.path === '/api/tasks',
      ).length,
      conversations: scenarioATerminalRefresh.filter(
        (item) => item.path === '/api/conversations',
      ).length,
      messages: scenarioATerminalRefresh.filter((item) =>
        /^\/api\/conversations\/\d+\/messages(?:\/page)?$/.test(item.path),
      ).length,
    },
  };
  console.log(JSON.stringify(scenarioAEvidence, null, 2));
  assert.ok(scenarioAAbort, 'scenario A did not actively abort SSE');
  assert.ok(
    scenarioA.timeline.some(
      (item) =>
        item.phase === 'first-sse-body-error' ||
        item.phase === 'first-sse-body-cancelled',
    ),
    'scenario A aborted SSE did not exit',
  );
  assert.equal(
    scenarioAEvidence.submitRequestCount,
    1,
    'scenario A must submit exactly once',
  );
  if (
    scenarioAEvidence.submitReturnedTaskId &&
    scenarioAEvidence.eventsObservedTaskId
  ) {
    assert.equal(
      scenarioAEvidence.submitReturnedTaskId,
      scenarioAEvidence.eventsObservedTaskId,
      'scenario A submit/events taskId mismatch',
    );
  }
  assert.deepEqual(
    scenarioA.state.submittedConversationIds,
    [scenarioAConversationId],
    'scenario A task used the wrong conversation',
  );
  assert.equal(
    scenarioAHealthyPolling.length,
    0,
    `scenario A polled while SSE was healthy: ${scenarioAHealthyPolling.length}`,
  );
  assert.ok(
    scenarioAFallback.length >= 2,
    `scenario A expected at least two fallback polls, got ${scenarioAFallback.length}`,
  );
  assert.ok(
    scenarioAFallbackGaps.every((gap) => gap >= 4000 && gap <= 6500),
    `scenario A fallback cadence invalid: ${scenarioAFallbackGaps}`,
  );
  assert.ok(
    Object.values(scenarioAEvidence.terminalRefreshCounts).every(
      (count) => count <= 1,
    ),
    `scenario A terminal refresh loop: ${JSON.stringify(scenarioAEvidence.terminalRefreshCounts)}`,
  );
  if (
    scenarioA.state.terminalStatus === 'ERROR' ||
    scenarioA.state.terminalStatus === 'FAILED'
  ) {
    throw new Error(
      `SCENARIO_A_TASK_ERROR taxonomy=${scenarioA.state.taskErrorTaxonomy || 'MODEL_ERROR_OTHER'}`,
    );
  }

  // A page reload gives Scenario B fresh injected state and closes every
  // stream/timer owned by Scenario A without changing production behavior.
  await page.evaluate(() => sessionStorage.setItem('p25ScenarioMode', 'B'));
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForURL((url) => url.pathname === '/agentmesh/workspace', {
    timeout: 20_000,
  });

  const newTaskButton = await requireUniqueVisible(
    '.new-task',
    'new QA conversation',
  );
  await newTaskButton.click();
  await page.waitForFunction(
    () => Number(window.__p25State.newConversationId) > 0,
    null,
    { timeout: 20_000 },
  );
  const newConversationId = await page.evaluate(
    () => window.__p25State.newConversationId,
  );
  await page
    .locator('.conversation-row.active')
    .filter({ hasText: 'P25 QA B' })
    .waitFor({ state: 'visible', timeout: 20_000 });
  console.log(
    `[P25 browser] QA conversation created; conversationId=${newConversationId}`,
  );
  const promptInput = await requireUniqueVisible(
    '.composer-card textarea',
    'workspace prompt',
  );
  const runButton = await requireUniqueVisible(
    '.composer-toolbar .el-button--primary',
    'workspace run',
  );
  const assistantCountBefore = await page
    .locator('.message-block.assistant')
    .count();
  const userCountBefore = await page.locator('.message-block.user').count();
  assert.equal(
    assistantCountBefore,
    0,
    'fresh QA conversation already contains assistant history',
  );
  assert.equal(
    userCountBefore,
    0,
    'fresh QA conversation already contains user history',
  );
  await promptInput.fill(process.env.P25_QA_PROMPT || mediumPrompt);
  await page.evaluate(() =>
    window.__p25Timeline.push({
      at: performance.now(),
      phase: 'submit-clicked',
    }),
  );
  await runButton.click();
  await waitForFirstSSE('SCENARIO_B', newConversationId);
  await page.waitForFunction(
    () => window.__p25State.abortRequested || window.__p25State.terminalStatus,
    null,
    { timeout: 30_000 },
  );
  if (!(await page.evaluate(() => window.__p25State.abortRequested)))
    throw new Error('SCENARIO_TOO_FAST');
  await page.waitForFunction(
    () => Boolean(window.__p25State.firstFallbackStatus),
    null,
    { timeout: 15_000 },
  );
  const firstFallbackStatus = await page.evaluate(
    () => window.__p25State.firstFallbackStatus,
  );
  if (firstFallbackStatus !== 'RUNNING') throw new Error('SCENARIO_TOO_FAST');
  await page.waitForFunction(
    () =>
      window.__p25Timeline.some(
        (item) => item.phase === 'second-sse-connected',
      ),
    null,
    { timeout: 20_000 },
  );
  await page.waitForFunction(
    () => Boolean(window.__p25State.terminalStatus),
    null,
    { timeout: 90_000 },
  );
  await page.waitForTimeout(1500);

  const { timeline, state } = await page.evaluate(() => ({
    timeline: window.__p25Timeline,
    state: window.__p25State,
  }));
  const requests = (predicate) =>
    timeline.filter((item) => item.phase === 'request' && predicate(item.path));
  const isTaskRefresh = (path) => path === '/api/tasks';
  const isConversationRefresh = (path) => path === '/api/conversations';
  const isMessageRefresh = (path) =>
    /^\/api\/conversations\/\d+\/messages(?:\/page)?$/.test(path);
  const isRefresh = (path) =>
    isTaskRefresh(path) ||
    isConversationRefresh(path) ||
    isMessageRefresh(path);
  const events = requests((path) => /\/api\/tasks\/\d+\/events$/.test(path));
  const tasks = requests(isTaskRefresh);
  const conversations = requests(isConversationRefresh);
  const messages = requests(isMessageRefresh);
  const submits = requests((path) => path === '/api/tasks/submit-stream');
  const firstConnected = timeline.find(
    (item) => item.phase === 'first-sse-connected',
  );
  const forcedAbort = timeline.find(
    (item) => item.phase === 'forced-sse-abort',
  );
  const bodyExit = timeline.find(
    (item) =>
      item.phase === 'first-sse-body-error' ||
      item.phase === 'first-sse-body-cancelled',
  );
  const secondConnected = timeline.find(
    (item) => item.phase === 'second-sse-connected',
  );
  const blockedReconnects = timeline.filter(
    (item) => item.phase === 'reconnect-attempt-blocked',
  );
  const fallback = timeline
    .filter((item) => item.phase === 'fallback-poll')
    .map((item) => item.at);
  const fallbackGaps = fallback
    .slice(1)
    .map((at, index) => at - fallback[index]);
  const fallbackAfterReconnect = timeline.filter(
    (item) =>
      item.phase === 'fallback-poll' &&
      secondConnected &&
      item.at > secondConnected.at,
  );
  const ordinals = state.deltaOrdinals.filter(Number.isFinite);
  const missingCount =
    ordinals.length > 0
      ? Math.max(...ordinals) -
        Math.min(...ordinals) +
        1 -
        new Set(ordinals).size
      : 0;
  const assistantCountAfter = await page
    .locator('.message-block.assistant')
    .count();
  const userCountAfter = await page.locator('.message-block.user').count();
  const finalAssistantText = await page
    .locator('.message-block.assistant .message-content')
    .last()
    .textContent()
    .catch(() => '');
  const healthyRequests = timeline.filter(
    (item) =>
      firstConnected &&
      forcedAbort &&
      item.phase === 'request' &&
      item.at > firstConnected.at &&
      item.at < forcedAbort.at,
  );
  const terminal = timeline.find((item) => item.phase === 'terminal-status');
  const afterReconnectBeforeTerminal = timeline.filter(
    (item) =>
      secondConnected &&
      terminal &&
      item.phase === 'request' &&
      item.at > secondConnected.at &&
      item.at < terminal.at,
  );
  const terminalRefresh = timeline.filter(
    (item) => item.phase === 'terminal-refresh',
  );
  const reconnectFirstDelta = timeline.find(
    (item) =>
      secondConnected &&
      item.phase === 'delta-frame' &&
      item.at > secondConnected.at,
  );
  const evidence = {
    sseConnectedDurationMs:
      forcedAbort && firstConnected ? forcedAbort.at - firstConnected.at : null,
    tasksRequestCount: tasks.length,
    conversationRequestCount: conversations.length,
    messageRequestCount: messages.length,
    eventsRequestCount: events.length,
    fallbackTimestampsMs: fallback,
    fallbackGapsMs: fallbackGaps,
    fallbackAfterReconnectCount: fallbackAfterReconnect.length,
    disconnectCursor: forcedAbort?.cursor || '0',
    disconnectWindowEndMs: forcedAbort?.disconnectUntil || null,
    blockedReconnectAttemptCount: blockedReconnects.length,
    resumeCursor: secondConnected?.cursor || '0',
    reconnectHttpStatus: secondConnected?.status || null,
    reconnectContentType: secondConnected?.contentType || '',
    eventTaskIds: [...new Set(state.eventTaskIds)],
    receivedOrdinals: ordinals,
    duplicateCount: state.duplicateCount,
    missingCount,
    executionIds: [...new Set(state.executionIds)],
    fences: [...new Set(state.fences)],
    terminalStatus: state.terminalStatus,
    taskErrorTaxonomy: state.taskErrorTaxonomy || '',
    newConversationId,
    submittedConversationIds: state.submittedConversationIds,
    userMessageDelta: userCountAfter - userCountBefore,
    assistantMessageDelta: assistantCountAfter - assistantCountBefore,
    ...submitSummary(newConversationId),
    eventsObservedTaskId: state.eventsObservedTaskId || 0,
    reconnectFirstAuthoritativeOrdinal: reconnectFirstDelta?.ordinal || null,
    reconnectExecutionId: reconnectFirstDelta?.executionId || '',
    reconnectFenceEpoch: reconnectFirstDelta?.fenceEpoch ?? null,
    healthyPhasePollingCount: healthyRequests.filter((item) =>
      isRefresh(item.path),
    ).length,
    reconnectPhasePollingCount: afterReconnectBeforeTerminal.filter((item) =>
      isRefresh(item.path),
    ).length,
    terminalRefreshCounts: {
      tasks: terminalRefresh.filter((item) => isTaskRefresh(item.path)).length,
      conversations: terminalRefresh.filter((item) =>
        isConversationRefresh(item.path),
      ).length,
      messages: terminalRefresh.filter((item) => isMessageRefresh(item.path))
        .length,
    },
    finalAnswerMatchesStream:
      String(finalAssistantText || '')
        .normalize('NFKC')
        .replaceAll(/\s+/g, ' ')
        .trim() ===
      String(state.assistantText || '')
        .normalize('NFKC')
        .replaceAll(/\s+/g, ' ')
        .trim(),
    timeline,
  };
  console.log(JSON.stringify(evidence, null, 2));
  if (
    timeline.some(
      (item) => item.phase === 'scenario-task-completed-before-disconnect',
    )
  ) {
    if (state.terminalStatus === 'ERROR' || state.terminalStatus === 'FAILED') {
      throw new Error(
        `SCENARIO_TASK_ERROR_BEFORE_DISCONNECT taxonomy=${state.taskErrorTaxonomy || 'MODEL_ERROR_OTHER'}`,
      );
    }
    throw new Error('SCENARIO_TOO_FAST');
  }
  const terminatedDuringDisconnect =
    forcedAbort &&
    bodyExit &&
    blockedReconnects.length > 0 &&
    fallback.length > 0 &&
    terminal &&
    terminal.at < forcedAbort.disconnectUntil &&
    !secondConnected;
  if (terminatedDuringDisconnect) {
    if (state.terminalStatus === 'ERROR' || state.terminalStatus === 'FAILED') {
      throw new Error(
        `SCENARIO_TASK_ERROR_DURING_DISCONNECT taxonomy=${state.taskErrorTaxonomy || 'MODEL_ERROR_OTHER'}`,
      );
    }
    throw new Error('SCENARIO_TASK_COMPLETED_DURING_DISCONNECT');
  }
  if (state.terminalStatus === 'ERROR' || state.terminalStatus === 'FAILED') {
    throw new Error(
      `SCENARIO_TASK_ERROR taxonomy=${state.taskErrorTaxonomy || 'MODEL_ERROR_OTHER'}`,
    );
  }
  assert.ok(
    forcedAbort && bodyExit,
    'QA_RUNNER_DEFECT: first active SSE did not actually abort',
  );
  assert.ok(events.length >= 2, `expected SSE reconnect, got ${events.length}`);
  assert.equal(
    secondConnected?.taskId,
    state.originalTaskId,
    'SSE reconnect changed taskId',
  );
  assert.equal(
    secondConnected?.status,
    200,
    `reconnect HTTP status=${secondConnected?.status}`,
  );
  assert.match(
    secondConnected?.contentType || '',
    /^text\/event-stream\b/i,
    'reconnect must return text/event-stream',
  );
  assert.equal(
    new Set(state.eventTaskIds).size,
    1,
    `reconnect changed task: ${state.eventTaskIds}`,
  );
  assert.notEqual(
    evidence.resumeCursor,
    '0',
    'reconnect cursor must be non-zero',
  );
  assert.equal(
    submits.length,
    1,
    `durable task submitted ${submits.length} times`,
  );
  if (evidence.submitReturnedTaskId && evidence.eventsObservedTaskId) {
    assert.equal(
      evidence.submitReturnedTaskId,
      evidence.eventsObservedTaskId,
      'scenario B submit/events taskId mismatch',
    );
  }
  assert.deepEqual(
    state.submittedConversationIds,
    [newConversationId],
    'durable task did not belong to fresh QA conversation',
  );
  assert.equal(
    state.duplicateCount,
    0,
    'duplicate authoritative delta observed',
  );
  assert.equal(
    missingCount,
    0,
    `missing authoritative delta count=${missingCount}`,
  );
  assert.ok(
    ordinals.length >= 2,
    `scenario B aborted before two deltas: ${ordinals}`,
  );
  assert.ok(
    ordinals.every(
      (ordinal, index) => index === 0 || ordinal > ordinals[index - 1],
    ),
    `authoritative ordinal moved backward: ${ordinals}`,
  );
  assert.equal(
    state.terminalStatus,
    'COMPLETED',
    `terminal status=${state.terminalStatus}`,
  );
  assert.equal(
    evidence.userMessageDelta,
    1,
    `user message delta=${evidence.userMessageDelta}`,
  );
  assert.equal(
    evidence.assistantMessageDelta,
    1,
    `assistant message delta=${evidence.assistantMessageDelta}`,
  );
  assert.equal(
    evidence.executionIds.length,
    1,
    `executionId changed without failover: ${evidence.executionIds}`,
  );
  assert.equal(
    evidence.fences.length,
    1,
    `fence changed without failover: ${evidence.fences}`,
  );
  assert.equal(
    evidence.healthyPhasePollingCount,
    0,
    `polling occurred while SSE healthy: ${evidence.healthyPhasePollingCount}`,
  );
  assert.equal(
    evidence.reconnectPhasePollingCount,
    0,
    `fallback continued after SSE reconnect: ${evidence.reconnectPhasePollingCount}`,
  );
  assert.ok(
    fallback.length > 0,
    `expected disconnected fallback task request, got ${fallback.length}`,
  );
  assert.ok(
    fallback[0] - forcedAbort.at > 0,
    `first fallback preceded disconnect: ${fallback[0] - forcedAbort.at}ms`,
  );
  assert.ok(
    fallback[0] - forcedAbort.at <= 5500,
    `first fallback missed the active interval window: ${fallback[0] - forcedAbort.at}ms`,
  );
  assert.ok(
    fallback[0] < secondConnected.at,
    'first fallback must occur before SSE reconnect',
  );
  assert.ok(
    fallbackGaps.every((gap) => gap >= 4500),
    `fallback cadence too fast: ${fallbackGaps}`,
  );
  assert.ok(
    fallbackGaps.every((gap) => gap <= 5500),
    `fallback cadence too slow: ${fallbackGaps}`,
  );
  assert.equal(
    fallbackAfterReconnect.length,
    0,
    `fallback continued after reconnect: ${fallbackAfterReconnect.length}`,
  );
  assert.ok(
    Object.values(evidence.terminalRefreshCounts).every((count) => count <= 1),
    `terminal refresh loop detected: ${JSON.stringify(evidence.terminalRefreshCounts)}`,
  );
  assert.equal(
    evidence.finalAnswerMatchesStream,
    true,
    'persisted final answer differs from streamed answer',
  );
} catch (error) {
  try {
    const diagnostic = await page.evaluate(() => {
      const state = window.__p25State || {};
      const { assistantText = '', ...safeState } = state;
      return {
        currentUrl: location.href,
        timeline: window.__p25Timeline || [],
        state: { ...safeState, assistantTextLength: assistantText.length },
      };
    });
    console.error('[P25 browser] failure evidence follows');
    console.error(JSON.stringify(diagnostic, null, 2));
  } catch (diagnosticError) {
    console.error(
      `[P25 browser] safe diagnostic unavailable at ${page.url()}: ${diagnosticError.message}`,
    );
  }
  console.error('[P25 browser] safe submit summaries');
  console.error(
    JSON.stringify(
      [...new Set(submitEvidence.map((item) => item.conversationId))]
        .filter((conversationId) => conversationId > 0)
        .map((conversationId) => ({
          conversationId,
          ...submitSummary(conversationId),
        })),
      null,
      2,
    ),
  );
  throw error;
} finally {
  await browser.close();
}
