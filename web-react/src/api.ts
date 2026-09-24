import type {
  Agent,
  Conversation,
  ConversationAttachment,
  CostSummary,
  RunCostRecord,
  DeliveryMode,
  ExecutionMode,
  KnowledgeBase,
  KnowledgeBaseScope,
  KnowledgeFile,
  MCPDiscoveredTool,
  MCPServer,
  MemoryCategory,
  MemorySourceType,
  Message,
  MessagePage,
  Planner,
  PluginInfo,
  Project,
  ProjectRuntimeConfig,
  RunResult,
  RuntimeReliabilitySnapshot,
  RuntimeTopologySnapshot,
  Scheduler,
  ServiceAccount,
  ServiceAccountCredential,
  EcosystemOverview,
  EcosystemPackage,
  EcosystemPackageBundle,
  EcosystemPackageDetail,
  EcosystemPackageManifest,
  ProjectPackageInstallation,
  SynthesisMode,
  Task,
  Tool,
  User,
  UserMemory,
} from "./types";

// Browser-facing API defaults to same-origin in both development and production.
// - Vite dev server proxies /api -> Go control plane.
// - Production Gateway proxies /api -> Go control plane.
// This keeps the HttpOnly refresh cookie on the browser-facing site and makes
// F5 / hard refresh session restoration independent of localhost vs 127.0.0.1.
const DEFAULT_BASE = "";

const BASE = (
  import.meta.env.VITE_API_BASE_URL ??
  DEFAULT_BASE
).replace(
  /\/$/,
  "",
);

let accessToken = "";

let refreshPromise: Promise<boolean> | null = null;

// =========================================================
// Refresh Access Token
//
// 多个请求同时 401 时，只执行一次 Refresh。
// =========================================================

async function refreshAccess(): Promise<boolean> {
  if (refreshPromise) {
    return refreshPromise;
  }

  refreshPromise = (async () => {
    try {
      const response = await fetch(
        `${BASE}/api/auth/refresh`,
        {
          method: "POST",
          credentials: "include",
        },
      );

      if (!response.ok) {
        accessToken = "";

        return false;
      }

      const body = await response.json();

      accessToken = body.data.accessToken;

      return true;
    } finally {
      refreshPromise = null;
    }
  })();

  return refreshPromise;
}

// =========================================================
// Unified Request
// =========================================================

async function request<T>(
  path: string,
  init: RequestInit = {},
  retry = true,
): Promise<T> {
  const headers = new Headers(
    init.headers,
  );

  if (accessToken) {
    headers.set(
      "Authorization",
      `Bearer ${accessToken}`,
    );
  }

  if (
    init.body &&
    !(init.body instanceof FormData) &&
    !headers.has("Content-Type")
  ) {
    headers.set(
      "Content-Type",
      "application/json; charset=utf-8",
    );
  }

  const response = await fetch(
    `${BASE}${path}`,
    {
      ...init,
      headers,
      credentials: "include",
    },
  );

  // =====================================================
  // Access Token expired
  //
  // request
  //   ↓ 401
  // refresh
  //   ↓
  // retry once
  // =====================================================

  if (
    response.status === 401 &&
    retry &&
    (await refreshAccess())
  ) {
    return request<T>(
      path,
      init,
      false,
    );
  }

  if (!response.ok) {
    throw await readApiError(
      response,
    );
  }

  const body = await response.json();

  return body.data as T;
}

// =========================================================
// Auth
// =========================================================

export type VerificationScene =
  | "register"
  | "login"
  | "reset_password";

export type EmailCodeResult = {
  expiresInSeconds: number;
  cooldownSeconds: number;
};

type AuthResponse = {
  accessToken: string;
  expiresIn: number;
  tokenType: string;
  user: User;
};

export class ApiError extends Error {
  readonly status: number;
  readonly code: number | null;

  constructor(
    message: string,
    status: number,
    code: number | null,
  ) {
    super(message);

    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

export function friendlyApiError(
  error: unknown,
  fallback = "操作失败，请稍后重试。",
) {
  if (error instanceof ApiError) {
    const normalizedMessage = error.message.trim();

    if (
      error.code === 50210 ||
      /runtime returned\s+\d+|internal server error/i.test(normalizedMessage)
    ) {
      return "Agent Runtime 执行失败，请稍后重试；如果持续失败，请查看运行详情或服务日志。";
    }

    if (normalizedMessage === "model provider not configured") {
      return "请先在模型设置中启用至少一个可用模型服务。";
    }

    if (error.status === 401) {
      return "登录状态已失效，请重新登录。";
    }

    if (error.status === 403) {
      return "你没有权限执行此操作。";
    }

    if (error.status === 404) {
      return "请求的资源不存在，或已经被移除。";
    }

    if (error.status === 409) {
      // Execution Routing clarification is a safe non-execution result, not an
      // idempotency conflict. Preserve its targeted question for the user.
      if (error.code === 40923) {
        return error.message.trim() || "请补充完成当前请求所需的信息。";
      }
      if (error.code === 40920) {
        return "请先在模型设置中启用至少一个可用模型服务。";
      }
      if (error.code === 40921) {
        return "请至少将一个已启用的个人模型服务加入自动路由，或在工作台手动指定模型。";
      }
      if (error.code === 40930) {
        return "当前项目已经属于另一个团队。一个项目同时只能属于一个团队；如需更换团队，请先完成项目迁移。";
      }
      return "当前数据已发生变化，请刷新后重试。";
    }

    if (error.status === 429) {
      return "当前项目额度或请求频率已达到限制，请稍后再试或联系管理员调整额度。";
    }

    if (error.status >= 500) {
      return "服务暂时不可用，请稍后重试。";
    }

    if (error.message.trim()) {
      return error.message.trim();
    }
  }

  if (error instanceof TypeError) {
    return "无法连接 AgentMesh 服务，请检查网络或服务状态。";
  }

  return error instanceof Error && error.message.trim()
    ? error.message.trim()
    : fallback;
}

type ErrorEnvelope = {
  code?: number;
  message?: string;
};

async function readApiError(
  response: Response,
): Promise<ApiError> {
  const text =
    await response.text();

  if (!text) {
    return new ApiError(
      `HTTP ${response.status}`,
      response.status,
      null,
    );
  }

  try {
    const body =
      JSON.parse(
        text,
      ) as ErrorEnvelope;

    return new ApiError(
      typeof body.message ===
          "string" &&
        body.message.trim()
        ? body.message.trim()
        : `HTTP ${response.status}`,
      response.status,
      typeof body.code ===
        "number"
        ? body.code
        : null,
    );
  } catch {
    return new ApiError(
      text,
      response.status,
      null,
    );
  }
}

function networkError(
  error: unknown,
): Error {
  if (
    error instanceof DOMException &&
    error.name ===
      "AbortError"
  ) {
    return new Error(
      "请求超时，请确认网络和 AgentMesh 服务状态后重试",
    );
  }

  if (
    error instanceof TypeError
  ) {
    return new Error(
      "无法连接 AgentMesh 服务，请确认后端已启动或稍后重试",
    );
  }

  return error instanceof Error
    ? error
    : new Error(
        String(error),
      );
}

async function publicJson<T>(
  path: string,
  body: Record<
    string,
    unknown
  >,
): Promise<T> {
  const controller =
    new AbortController();

  const timer =
    window.setTimeout(
      () =>
        controller.abort(),
      20_000,
    );

  try {
    const response =
      await fetch(
        `${BASE}${path}`,
        {
          method: "POST",

          credentials:
            "include",

          signal:
            controller.signal,

          headers: {
            "Content-Type":
              "application/json; charset=utf-8",
          },

          body:
            JSON.stringify(
              body,
            ),
        },
      );

    if (!response.ok) {
      throw await readApiError(
        response,
      );
    }

    const envelope =
      (await response.json()) as {
        data: T;
      };

    return envelope.data;
  } catch (error) {
    if (
      error instanceof ApiError
    ) {
      throw error;
    }

    throw networkError(
      error,
    );
  } finally {
    window.clearTimeout(
      timer,
    );
  }
}

function acceptAuth(
  result: AuthResponse,
): User {
  accessToken =
    result.accessToken;

  return result.user;
}

export async function login(
  email: string,
  password: string,
): Promise<User> {
  const result =
    await publicJson<AuthResponse>(
      "/api/auth/login",
      {
        email,
        password,
      },
    );

  return acceptAuth(
    result,
  );
}

export async function sendEmailCode(
  email: string,
  scene: VerificationScene,
): Promise<EmailCodeResult> {
  return publicJson<EmailCodeResult>(
    "/api/auth/email/code",
    {
      email,
      scene,
    },
  );
}

export async function registerVerified(
  email: string,
  code: string,
  password: string,
  displayName: string,
): Promise<User> {
  const result =
    await publicJson<AuthResponse>(
      "/api/auth/register/verify",
      {
        email,
        code,
        password,
        displayName,
      },
    );

  return acceptAuth(
    result,
  );
}

export async function loginWithCode(
  email: string,
  code: string,
): Promise<User> {
  const result =
    await publicJson<AuthResponse>(
      "/api/auth/login/code",
      {
        email,
        code,
      },
    );

  return acceptAuth(
    result,
  );
}

export async function resetPassword(
  email: string,
  code: string,
  newPassword: string,
): Promise<void> {
  await publicJson<null>(
    "/api/auth/password/reset",
    {
      email,
      code,
      newPassword,
    },
  );

  accessToken = "";
}

export async function logout() {
  await fetch(
    `${BASE}/api/auth/logout`,
    {
      method: "POST",
      credentials: "include",
    },
  );

  accessToken = "";
}

export const me = () =>
  request<User>(
    "/api/me",
  );

// =========================================================
// Conversation
// =========================================================

export const listConversations = () =>
  request<Conversation[]>(
    "/api/conversations",
  );

export const createConversation = (
  title = "新会话",
) =>
  request<Conversation>(
    "/api/conversations",
    {
      method: "POST",

      body: JSON.stringify({
        title,
      }),
    },
  );

export const renameConversation = (
  conversationId: number,
  title: string,
) =>
  request<Conversation>(
    `/api/conversations/${conversationId}`,
    {
      method: "PATCH",

      body: JSON.stringify({
        title,
      }),
    },
  );

export const deleteConversation = (
  conversationId: number,
) =>
  request<null>(
    `/api/conversations/${conversationId}`,
    {
      method: "DELETE",
    },
  );

export const listMessages = (
  id: number,
) =>
  request<Message[]>(
    `/api/conversations/${id}/messages`,
  );

export const listMessagePage = (
  id: number,
  options: {
    beforeId?: number | null;
    limit?: number;
  } = {},
) => {
  const params = new URLSearchParams();
  params.set("limit", String(options.limit ?? 50));
  if (options.beforeId != null) {
    params.set("beforeId", String(options.beforeId));
  }
  return request<MessagePage>(
    `/api/conversations/${id}/messages/page?${params.toString()}`,
  );
};


// =========================================================
// Projects / Workspace Organization
// =========================================================

export const listProjects = () =>
  request<Project[]>(
    "/api/projects",
  );

export const createProject = (
  name: string,
  description = "",
) =>
  request<Project>(
    "/api/projects",
    {
      method: "POST",

      body: JSON.stringify({
        name,
        description,
      }),
    },
  );

export const updateProject = (
  projectId: number,
  name: string,
  description = "",
) =>
  request<Project>(
    `/api/projects/${projectId}`,
    {
      method: "PATCH",

      body: JSON.stringify({
        name,
        description,
      }),
    },
  );

export const deleteProject = (
  projectId: number,
) =>
  request<null>(
    `/api/projects/${projectId}`,
    {
      method: "DELETE",
    },
  );

export const moveConversationToProject = (
  conversationId: number,
  projectId: number,
) =>
  request<null>(
    `/api/projects/${projectId}/conversations/${conversationId}`,
    {
      method: "PUT",
    },
  );

export const removeConversationFromProject = (
  conversationId: number,
) =>
  request<null>(
    `/api/projects/conversations/${conversationId}`,
    {
      method: "DELETE",
    },
  );

// =========================================================
// Project Runtime Context
// =========================================================

export const getProjectRuntimeConfig = (
  projectId: number,
) =>
  request<ProjectRuntimeConfig>(
    `/api/projects/${projectId}/runtime`,
  );

export const updateProjectRuntimeConfig = (
  projectId: number,
  config: ProjectRuntimeConfig,
) =>
  request<ProjectRuntimeConfig>(
    `/api/projects/${projectId}/runtime`,
    {
      method: "PUT",
      body: JSON.stringify(
        config,
      ),
    },
  );

// =========================================================
// Knowledge Bases / Files
// =========================================================

export const listKnowledgeBases = () =>
  request<KnowledgeBase[]>(
    "/api/knowledge/bases",
  );

export const createKnowledgeBase = (
  name: string,
  description: string,
  scope: KnowledgeBaseScope,
  projectId: number | null = null,
) =>
  request<KnowledgeBase>(
    "/api/knowledge/bases",
    {
      method: "POST",
      body: JSON.stringify({
        name,
        description,
        scope,
        projectId,
      }),
    },
  );

export const updateKnowledgeBase = (
  knowledgeBaseId: number,
  name: string,
  description: string,
) =>
  request<KnowledgeBase>(
    `/api/knowledge/bases/${knowledgeBaseId}`,
    {
      method: "PATCH",
      body: JSON.stringify({
        name,
        description,
      }),
    },
  );

export const deleteKnowledgeBase = (
  knowledgeBaseId: number,
) =>
  request<null>(
    `/api/knowledge/bases/${knowledgeBaseId}`,
    {
      method: "DELETE",
    },
  );

export const listKnowledgeFiles = () =>
  request<KnowledgeFile[]>(
    "/api/knowledge/files",
  );

export const listKnowledgeBaseFiles = (
  knowledgeBaseId: number,
) =>
  request<KnowledgeFile[]>(
    `/api/knowledge/bases/${knowledgeBaseId}/files`,
  );

export const uploadKnowledgeBaseFile = (
  knowledgeBaseId: number,
  file: File,
) => {
  const body = new FormData();
  body.append("file", file);

  return request<KnowledgeFile>(
    `/api/knowledge/bases/${knowledgeBaseId}/files`,
    {
      method: "POST",
      body,
    },
  );
};

export const deleteKnowledgeBaseFile = (
  knowledgeBaseId: number,
  fileId: number,
) =>
  request<null>(
    `/api/knowledge/bases/${knowledgeBaseId}/files/${fileId}`,
    {
      method: "DELETE",
    },
  );

export const reindexKnowledgeFile = (
  fileId: number,
) =>
  request<KnowledgeFile>(
    `/api/knowledge/files/${fileId}/reindex`,
    {
      method: "POST",
    },
  );

// Project Home compatibility API: uses the Project's default PROJECT KB.
export const listProjectKnowledgeFiles = (
  projectId: number,
) =>
  request<KnowledgeFile[]>(
    `/api/projects/${projectId}/knowledge/files`,
  );

export const uploadProjectKnowledgeFile = (
  projectId: number,
  file: File,
) => {
  const body = new FormData();
  body.append("file", file);

  return request<KnowledgeFile>(
    `/api/projects/${projectId}/knowledge/files`,
    {
      method: "POST",
      body,
    },
  );
};

export const deleteProjectKnowledgeFile = (
  projectId: number,
  fileId: number,
) =>
  request<null>(
    `/api/projects/${projectId}/knowledge/files/${fileId}`,
    {
      method: "DELETE",
    },
  );

export const listProjectGlobalKnowledgeBindings = (
  projectId: number,
) =>
  request<KnowledgeBase[]>(
    `/api/projects/${projectId}/knowledge/global-bindings`,
  );

export const bindProjectGlobalKnowledgeBase = (
  projectId: number,
  knowledgeBaseId: number,
) =>
  request<null>(
    `/api/projects/${projectId}/knowledge/global-bindings/${knowledgeBaseId}`,
    {
      method: "PUT",
    },
  );

export const unbindProjectGlobalKnowledgeBase = (
  projectId: number,
  knowledgeBaseId: number,
) =>
  request<null>(
    `/api/projects/${projectId}/knowledge/global-bindings/${knowledgeBaseId}`,
    {
      method: "DELETE",
    },
  );


// =========================================================
// User-global Long-term Memory
// =========================================================

export type MemoryListFilters = {
  category?: MemoryCategory;
  status?: string;
  keyword?: string;
  limit?: number;
};

export type CreateMemoryRequest = {
  category: MemoryCategory;
  memoryKey: string;
  content: string;
  sourceType?: MemorySourceType;
  confidence?: number;
  status?: string;
};

export type UpdateMemoryRequest =
  Partial<CreateMemoryRequest>;

export const listMemories = (
  filters: MemoryListFilters = {},
) => {
  const params =
    new URLSearchParams();

  if (filters.category) {
    params.set(
      "category",
      filters.category,
    );
  }

  if (filters.status) {
    params.set(
      "status",
      filters.status,
    );
  }

  if (filters.keyword) {
    params.set(
      "keyword",
      filters.keyword,
    );
  }

  if (filters.limit != null) {
    params.set(
      "limit",
      String(filters.limit),
    );
  }

  const query =
    params.toString();

  return request<UserMemory[]>(
    `/api/memories${
      query ? `?${query}` : ""
    }`,
  );
};

export const getMemory = (
  memoryId: number,
) =>
  request<UserMemory>(
    `/api/memories/${memoryId}`,
  );

export const createMemory = (
  input: CreateMemoryRequest,
) =>
  request<UserMemory>(
    "/api/memories",
    {
      method: "POST",
      body: JSON.stringify(
        input,
      ),
    },
  );

export const updateMemory = (
  memoryId: number,
  input: UpdateMemoryRequest,
) =>
  request<UserMemory>(
    `/api/memories/${memoryId}`,
    {
      method: "PATCH",
      body: JSON.stringify(
        input,
      ),
    },
  );

export const deleteMemory = (
  memoryId: number,
) =>
  request<null>(
    `/api/memories/${memoryId}`,
    {
      method: "DELETE",
    },
  );

// =========================================================
// Agent
// =========================================================

export const listAgents = () =>
  request<Agent[]>(
    "/api/agents",
  );

export const seedDemoAgents = () =>
  request<Agent[]>(
    "/api/agents/seed-demo",
    {
      method: "POST",
    },
  );

export const createAgent = (
  agent: Partial<Agent>,
) =>
  request<Agent>(
    "/api/agents",
    {
      method: "POST",

      body: JSON.stringify(
        agent,
      ),
    },
  );

// =========================================================
// Task History
// =========================================================

export const listTasks = () =>
  request<Task[]>(
    "/api/tasks",
  );

export const deleteTask = (
  taskId: number,
) =>
  request<null>(
    `/api/tasks/${taskId}`,
    {
      method: "DELETE",
    },
  );

export const cancelTask = (
  taskId: number,
) =>
  request<Task>(
    `/api/tasks/${taskId}/cancel`,
    {
      method: "POST",
    },
  );

export const getRuntimeReliability = () =>
  request<RuntimeReliabilitySnapshot>(
    "/api/runtime/reliability",
  );

export const getRuntimeTopology = () =>
  request<RuntimeTopologySnapshot>(
    "/api/runtime/topology",
  );

// =========================================================
// Conversation Attachments
// Request-local files/images. These are not knowledge-base ingestion.
// =========================================================

async function uploadMultipart<T>(
  path: string,
  file: File,
  onProgress?: (percent: number) => void,
  retry = true,
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const body = new FormData();
    body.append("file", file);

    xhr.open("POST", `${BASE}${path}`);
    xhr.withCredentials = true;
    if (accessToken) xhr.setRequestHeader("Authorization", `Bearer ${accessToken}`);

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && event.total > 0) {
        onProgress?.(Math.min(100, Math.round((event.loaded / event.total) * 100)));
      }
    };

    xhr.onerror = () => reject(new TypeError("network upload failed"));
    xhr.onload = async () => {
      if (xhr.status === 401 && retry) {
        try {
          if (await refreshAccess()) {
            resolve(await uploadMultipart<T>(path, file, onProgress, false));
            return;
          }
        } catch (error) {
          reject(error);
          return;
        }
      }

      if (xhr.status < 200 || xhr.status >= 300) {
        let message = `HTTP ${xhr.status}`;
        let code: number | null = null;
        try {
          const parsed = JSON.parse(xhr.responseText || "{}") as ErrorEnvelope;
          if (typeof parsed.message === "string" && parsed.message.trim()) message = parsed.message.trim();
          if (typeof parsed.code === "number") code = parsed.code;
        } catch {
          if (xhr.responseText) message = xhr.responseText;
        }
        reject(new ApiError(message, xhr.status, code));
        return;
      }

      try {
        const envelope = JSON.parse(xhr.responseText) as { data: T };
        onProgress?.(100);
        resolve(envelope.data);
      } catch {
        reject(new ApiError("上传响应格式不正确", xhr.status, null));
      }
    };

    xhr.send(body);
  });
}

export const uploadConversationAttachment = (
  conversationId: number,
  file: File,
  onProgress?: (percent: number) => void,
) => uploadMultipart<ConversationAttachment>(
  `/api/conversations/${conversationId}/attachments`,
  file,
  onProgress,
);

export const listConversationAttachments = (conversationId: number) =>
  request<ConversationAttachment[]>(`/api/conversations/${conversationId}/attachments`);

export const deleteConversationAttachment = (conversationId: number, attachmentId: number) =>
  request<void>(`/api/conversations/${conversationId}/attachments/${attachmentId}`, { method: "DELETE" });

// =========================================================
// Run New Task
// =========================================================

export type RunTaskRequest = {
  conversationId: number | null;

  // The same key must survive a transport/auth retry of one user action.
  clientRequestId?: string;

  task: string;

  scheduler: Scheduler;

  planner: Planner;

  executionMode: ExecutionMode;

  synthesisMode: SynthesisMode;

  deliveryMode: DeliveryMode;

  ragPolicy?: import("./types").RagPolicy;

  modelSelection?: import("./types").ModelSelection;

  maxLatencyMs: number;

  maxCost: number;

  minQuality: number;

  retryOnWorkerLoss?: boolean;

  attachmentIds?: number[];
};

export type RunTaskStreamCallbacks = {
  onDelta?: (delta: string) => void;
  onStatus?: (message: string) => void;
  onReady?: () => void;
};

type RunTaskStreamEvent = {
  type?: string;
  mode?: "direct" | "durable";
  reason?: string;
  delta?: string;
  message?: string;
  phase?: string;
  trace?: { title?: string; status?: string; detail?: string; kind?: string; elapsedMs?: number };
  result?: RunResult;
};

export async function runTaskStream(
  input: RunTaskRequest,
  callbacks: RunTaskStreamCallbacks = {},
  retry = true,
): Promise<RunResult> {
  const clientRequestId = input.clientRequestId ?? crypto.randomUUID();
  const headers = new Headers({ "Content-Type": "application/json; charset=utf-8" });
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);

  // AUTO is decided and submitted atomically by Go. The legacy direct
  // endpoint stays available to older clients and explicit overrides.
  const endpoint = input.deliveryMode === "auto"
    ? "/api/tasks/submit-stream"
    : "/api/tasks/run-stream";
  const response = await fetch(`${BASE}${endpoint}`, {
    method: "POST",
    credentials: "include",
    headers,
    body: JSON.stringify({
      conversationId: input.conversationId,
      clientRequestId,
      task: input.task,
      scheduler: input.scheduler,
      planner: input.planner,
      executionMode: input.executionMode,
      synthesisMode: input.synthesisMode,
      modelSelection: input.modelSelection ?? { mode: "auto" },
      ragPolicy: input.ragPolicy ?? { mode: "AUTO", scopes: ["PROJECT"], selectedKnowledgeBaseIds: [] },
      attachmentIds: input.attachmentIds ?? [],
      constraints: {
        maxLatencyMs: input.maxLatencyMs,
        maxCost: input.maxCost,
        minQuality: input.minQuality,
        retryOnWorkerLoss: input.retryOnWorkerLoss ?? false,
      },
    }),
  });

  if (response.status === 401 && retry && (await refreshAccess())) {
    return runTaskStream({ ...input, clientRequestId }, callbacks, false);
  }
  if (!response.ok) throw await readApiError(response);
  if (!response.body) throw new ApiError("服务器没有返回流式响应", 502, null);

  callbacks.onReady?.();
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalResult: RunResult | null = null;

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split(/\r?\n/);
    buffer = lines.pop() ?? "";

    for (const raw of lines) {
      const line = raw.trim();
      if (!line) continue;
      let event: RunTaskStreamEvent;
      try {
        event = JSON.parse(line) as RunTaskStreamEvent;
      } catch {
        continue;
      }
      if (event.type === "delta" && event.delta) callbacks.onDelta?.(event.delta);
      if (event.type === "route" && event.mode === "durable") {
        callbacks.onStatus?.("任务已进入可靠队列，后台继续执行…");
      }
      if (event.type === "status" && event.message) callbacks.onStatus?.(event.message);
      if (event.type === "trace" && event.trace?.title) {
        callbacks.onStatus?.(event.trace.title);
      }
      if (event.type === "ready") callbacks.onStatus?.("模型已连接，正在生成回答…");
      if (event.type === "error") {
        const message = event.message || "任务执行失败";
        if (message === "model provider not configured") {
          throw new ApiError(message, 409, 40920);
        }
        throw new ApiError(message, 502, 50210);
      }
      if (event.type === "result" && event.result) finalResult = event.result;
    }
  }

  if (buffer.trim()) {
    try {
      const event = JSON.parse(buffer) as RunTaskStreamEvent;
      if (event.type === "result" && event.result) finalResult = event.result;
      if (event.type === "error") {
        const message = event.message || "任务执行失败";
        if (message === "model provider not configured") throw new ApiError(message, 409, 40920);
        throw new ApiError(message, 502, 50210);
      }
    } catch (error) {
      if (error instanceof ApiError) throw error;
    }
  }

  if (!finalResult) throw new ApiError("流式响应意外结束，请重试。", 502, null);
  return finalResult;
}

// Knowledge Runtime: one owner-scoped replay cursor for committed task states and sanitized
// worker phases. Never includes prompts, raw tool payloads or model deltas.
export type DurableTaskStateEvent = {
  sequence: number;
  taskId: number;
  status: string;
  jobStatus: string;
  fenceEpoch: number;
  eventType?: "state" | "trace";
  phase?: string;
  phaseStatus?: "running" | "completed" | "error" | "skipped";
  createdAt: string;
};

export async function subscribeDurableTaskEvents(
  taskId: number,
  after: number,
  onEvent: (event: DurableTaskStateEvent) => void,
  signal: AbortSignal,
  onConnected?: () => void,
  retryAuth = true,
): Promise<{ cursor: number; terminal: boolean }> {
  const headers = new Headers({ Accept: "text/event-stream", "Last-Event-ID": String(after) });
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  const response = await fetch(`${BASE}/api/tasks/${taskId}/events`, {
    method: "GET", credentials: "include", headers, signal,
  });
  if (response.status === 401 && retryAuth && (await refreshAccess())) {
    return subscribeDurableTaskEvents(taskId, after, onEvent, signal, onConnected, false);
  }
  if (!response.ok) throw await readApiError(response);
  if (!response.body) throw new ApiError("任务事件订阅不可用", 502, null);
  onConnected?.();
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let cursor = after;
  let terminal = false;
  const terminalStatuses = new Set([
    "COMPLETED", "ERROR", "FAILED", "CANCELED", "INPUT_REQUIRED", "AUTH_REQUIRED",
  ]);
  const acceptFrame = (frame: string) => {
    let id: number | null = null;
    let kind = "";
    let data = "";
    for (const line of frame.split("\n")) {
      if (line.startsWith("id:")) {
        const parsed = Number(line.slice(3).trim());
        if (Number.isSafeInteger(parsed) && parsed > 0) id = parsed;
      }
      if (line.startsWith("event:")) kind = line.slice(6).trim();
      if (line.startsWith("data:")) data += line.slice(5).trimStart();
    }
    if (kind === "access_lost") throw new ApiError("任务访问权限或事件服务已失效", 403, null);
    if (kind !== "task" || id == null || !data || id <= cursor) return;
    const event = JSON.parse(data) as DurableTaskStateEvent;
    if (event.sequence !== id || event.taskId !== taskId) return;
    cursor = id;
    terminal = terminalStatuses.has(event.status);
    onEvent(event);
  };
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        acceptFrame(buffer.slice(0, boundary));
        buffer = buffer.slice(boundary + 2);
        boundary = buffer.indexOf("\n\n");
      }
    }
    if (buffer.trim()) acceptFrame(buffer);
    return { cursor, terminal };
  } finally {
    reader.releaseLock();
  }
}

export type TaskExecutionRoute = {
  mode: "direct" | "durable";
  reason: string;
};

export const decideTaskExecutionRoute = (input: RunTaskRequest) =>
  request<TaskExecutionRoute>("/api/tasks/execution-route", {
    method: "POST",
    body: JSON.stringify({
      conversationId: input.conversationId,
      task: input.task,
      scheduler: input.scheduler,
      planner: input.planner,
      executionMode: input.executionMode,
      synthesisMode: input.synthesisMode,
      modelSelection: input.modelSelection ?? { mode: "auto" },
      ragPolicy: input.ragPolicy ?? { mode: "AUTO", scopes: ["PROJECT"], selectedKnowledgeBaseIds: [] },
      attachmentIds: input.attachmentIds ?? [],
      constraints: {
        maxLatencyMs: input.maxLatencyMs,
        maxCost: input.maxCost,
        minQuality: input.minQuality,
        retryOnWorkerLoss: input.retryOnWorkerLoss ?? false,
      },
    }),
  });

export const runTask = (
  input: RunTaskRequest,
) =>
  request<RunResult>(
    input.deliveryMode === "durable"
      ? "/api/tasks/run-durable"
      : "/api/tasks/run",
    {
      method: "POST",

      body: JSON.stringify({
        conversationId:
          input.conversationId,

        task: input.task,

        scheduler:
          input.scheduler,

        planner:
          input.planner,

        executionMode:
          input.executionMode,

        synthesisMode:
          input.synthesisMode,

        modelSelection:
          input.modelSelection ?? { mode: "auto" },

        ragPolicy:
          input.ragPolicy ?? { mode: "AUTO", scopes: ["PROJECT"], selectedKnowledgeBaseIds: [] },

        attachmentIds:
          input.attachmentIds ?? [],

        constraints: {
          maxLatencyMs:
            input.maxLatencyMs,

          maxCost:
            input.maxCost,

          minQuality:
            input.minQuality,

          retryOnWorkerLoss:
            input.retryOnWorkerLoss ?? false,
        },
      }),
    },
  );

// =========================================================
// Resume Existing Long-lived Task
//
// React only sends:
//
// {
//     task: supplementalInput
// }
//
// 不发送 continuation。
// =========================================================

export const resumeTask = (
  taskId: number,
  supplementalInput: string,
) =>
  request<RunResult>(
    `/api/tasks/${taskId}/resume`,
    {
      method: "POST",

      body: JSON.stringify({
        task:
          supplementalInput,
      }),
    },
  );

export const decideTaskApproval = (
  taskId: number,
  decision: "approve" | "reject",
) =>
  request<RunResult>(
    `/api/tasks/${taskId}/resume`,
    {
      method: "POST",
      body: JSON.stringify({
        decision,
      }),
    },
  );

// =========================================================
// Plugin
// =========================================================

export const listPlugins = () =>
  request<PluginInfo[]>(
    "/api/runtime/plugins",
  );

// =========================================================
// Tool
// =========================================================

export const listTools = () =>
  request<Tool[]>(
    "/api/tools",
  );

export const createTool = (
  tool: Partial<Tool>,
) =>
  request<Tool>(
    "/api/tools",
    {
      method: "POST",
      body: JSON.stringify(tool),
    },
  );

export const seedDemoTools = () =>
  request<Tool[]>(
    "/api/tools/seed-demo",
    {
      method: "POST",
    },
  );

export const seedDesktopTools = () =>
  request<Tool[]>(
    "/api/tools/seed-desktop",
    {
      method: "POST",
    },
  );

export const updateTool = (
  id: number,
  tool: Partial<Tool>,
) =>
  request<Tool>(
    `/api/tools/${id}`,
    {
      method: "PATCH",
      body: JSON.stringify(tool),
    },
  );

export const deleteTool = (
  id: number,
) =>
  request<void>(
    `/api/tools/${id}`,
    {
      method: "DELETE",
    },
  );

// =========================================================
// MCP Server
// =========================================================

export const listMCPServers = () =>
  request<MCPServer[]>(
    "/api/mcp-servers",
  );

export const createMCPServer = (
  server: Partial<MCPServer>,
) =>
  request<MCPServer>(
    "/api/mcp-servers",
    {
      method: "POST",

      body: JSON.stringify(
        server,
      ),
    },
  );

export const deleteMCPServer = (
  id: number,
) =>
  request<void>(
    `/api/mcp-servers/${id}`,
    {
      method: "DELETE",
    },
  );

export const seedDemoMCPServer =
  () =>
    request<MCPServer>(
      "/api/mcp-servers/seed-demo",
      {
        method: "POST",
      },
    );

export const discoverMCPTools =
  async (
    id: number,
  ) =>
    (
      await request<{
        tools: MCPDiscoveredTool[];
      }>(
        `/api/mcp-servers/${id}/discover`,
        {
          method: "POST",
        },
      )
    ).tools;
// =========================================================
// Personal model provider / BYOK
// =========================================================
export async function listUserModelServices() {
  return request<import("./types").UserModelService[]>("/api/me/model-services");
}

export async function createUserModelService(input: import("./types").UserModelServiceInput) {
  return request<import("./types").UserModelService>("/api/me/model-services", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function updateUserModelService(id: number, input: import("./types").UserModelServiceInput) {
  return request<import("./types").UserModelService>(`/api/me/model-services/${id}`, {
    method: "PUT",
    body: JSON.stringify(input),
  });
}

export async function deleteUserModelService(id: number) {
  return request<void>(`/api/me/model-services/${id}`, { method: "DELETE" });
}

export async function getUserModelProvider() {
  return request<import("./types").UserModelProvider | null>("/api/me/model-provider");
}

export async function upsertUserModelProvider(input: import("./types").UserModelProviderInput) {
  return request<import("./types").UserModelProvider>("/api/me/model-provider", {
    method: "PUT",
    body: JSON.stringify(input),
  });
}

export async function deleteUserModelProvider() {
  return request<void>("/api/me/model-provider", { method: "DELETE" });
}

// =========================================================
// Enterprise Governance
// =========================================================
export async function getProjectGovernance(projectId: number) {
  return request<import("./types").GovernanceOverview>(`/api/projects/${projectId}/governance`);
}

export type CostSummaryQuery = {
  from?: string;
  to?: string;
  provider?: string;
  model?: string;
};

function costSummaryParams(query?: CostSummaryQuery) {
  const params = new URLSearchParams();
  if (query?.from) params.set("from", query.from);
  if (query?.to) params.set("to", query.to);
  if (query?.provider) params.set("provider", query.provider);
  if (query?.model) params.set("model", query.model);
  return params.toString();
}

export async function getUserCostSummary(query?: CostSummaryQuery) {
  const params = costSummaryParams(query);
  return request<CostSummary>(`/api/costs/summary${params ? `?${params}` : ""}`);
}

export async function getProjectCostSummary(projectId: number, query?: CostSummaryQuery) {
  const params = costSummaryParams(query);
  return request<CostSummary>(`/api/projects/${projectId}/costs${params ? `?${params}` : ""}`);
}

export async function getRunCost(taskId: number) {
  return request<RunCostRecord>(`/api/tasks/${taskId}/cost`);
}
export async function addProjectMember(projectId: number, email: string, role: string) {
  return request<import("./types").ProjectMember>(`/api/projects/${projectId}/members`, {
    method: "POST",
    body: JSON.stringify({ email, role }),
  });
}
export async function removeProjectMember(projectId: number, userId: number) {
  return request<void>(`/api/projects/${projectId}/members/${userId}`, { method: "DELETE" });
}
export async function updateProjectQuota(projectId: number, quota: import("./types").ProjectQuota) {
  return request<import("./types").ProjectQuota>(`/api/projects/${projectId}/quota`, {
    method: "PUT",
    body: JSON.stringify(quota),
  });
}
export async function createProjectSecret(projectId: number, name: string, kind: string, value: string) {
  return request<import("./types").ProjectSecret>(`/api/projects/${projectId}/secrets`, {
    method: "POST",
    body: JSON.stringify({ name, kind, value }),
  });
}
export async function deleteProjectSecret(projectId: number, secretId: number) {
  return request<void>(`/api/projects/${projectId}/secrets/${secretId}`, { method: "DELETE" });
}
export async function upsertProjectModelProvider(projectId: number, provider: import("./types").ProjectModelProvider) {
  return request<import("./types").ProjectModelProvider>(`/api/projects/${projectId}/model-provider`, {
    method: "PUT",
    body: JSON.stringify(provider),
  });
}
export async function listOrganizations() {
  return request<import("./types").Organization[]>("/api/organizations");
}
export async function createOrganization(name: string) {
  return request<import("./types").Organization>("/api/organizations", { method: "POST", body: JSON.stringify({ name }) });
}
export async function addOrganizationMember(organizationId: number, email: string, role: string) {
  return request<unknown>(`/api/organizations/${organizationId}/members`, { method: "POST", body: JSON.stringify({ email, role }) });
}
export async function bindOrganizationProject(organizationId: number, projectId: number) {
  return request<void>(`/api/organizations/${organizationId}/projects/${projectId}`, { method: "PUT" });
}


// =========================================================
// V4 Platform Ecosystem
// =========================================================

export const getEcosystemOverview = () =>
  request<EcosystemOverview>(
    "/api/ecosystem/overview",
  );

export const searchEcosystemPackages = (
  query = "",
  kind = "",
) => {
  const params = new URLSearchParams();
  if (query.trim()) params.set("q", query.trim());
  if (kind.trim()) params.set("kind", kind.trim());
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return request<EcosystemPackage[]>(`/api/ecosystem/marketplace${suffix}`);
};

export const getEcosystemPackage = (slug: string) =>
  request<EcosystemPackageDetail>(
    `/api/ecosystem/packages/${encodeURIComponent(slug)}`,
  );

export const createEcosystemPackage = (input: {
  slug: string;
  name: string;
  kind: "AGENT" | "MCP" | "PLUGIN";
  summary: string;
  description: string;
  visibility: "PUBLIC" | "PRIVATE";
  version: string;
  manifest: EcosystemPackageManifest;
  publish: boolean;
}) =>
  request<EcosystemPackageDetail>(
    "/api/ecosystem/packages",
    {
      method: "POST",
      body: JSON.stringify(input),
    },
  );

export const validateEcosystemPackage = (
  kind: string,
  manifest: EcosystemPackageManifest,
) =>
  request<{
    valid: boolean;
    kind: string;
    schemaVersion: string;
    permissions: string[];
    checksum: string;
  }>(
    "/api/ecosystem/packages/validate",
    {
      method: "POST",
      body: JSON.stringify({ kind, manifest }),
    },
  );

export const exportEcosystemPackage = (
  slug: string,
  version = "",
) => {
  const suffix = version ? `?version=${encodeURIComponent(version)}` : "";
  return request<EcosystemPackageBundle>(
    `/api/ecosystem/packages/${encodeURIComponent(slug)}/export${suffix}`,
  );
};

export const importEcosystemPackage = (
  bundle: EcosystemPackageBundle,
) =>
  request<EcosystemPackageDetail>(
    "/api/ecosystem/import",
    {
      method: "POST",
      body: JSON.stringify(bundle),
    },
  );

export const listProjectInstallations = (
  projectId: number,
) =>
  request<ProjectPackageInstallation[]>(
    `/api/projects/${projectId}/ecosystem/installations`,
  );

export const installEcosystemPackage = (
  projectId: number,
  slug: string,
  version = "",
  config: Record<string, unknown> = {},
) =>
  request<ProjectPackageInstallation>(
    `/api/projects/${projectId}/ecosystem/installations`,
    {
      method: "POST",
      body: JSON.stringify({ slug, version, config }),
    },
  );

export const setProjectInstallationEnabled = (
  projectId: number,
  installationId: number,
  enabled: boolean,
) =>
  request<ProjectPackageInstallation>(
    `/api/projects/${projectId}/ecosystem/installations/${installationId}`,
    {
      method: "PATCH",
      body: JSON.stringify({ enabled }),
    },
  );

export const deleteProjectInstallation = (
  projectId: number,
  installationId: number,
) =>
  request<void>(
    `/api/projects/${projectId}/ecosystem/installations/${installationId}`,
    { method: "DELETE" },
  );

export const listServiceAccounts = (
  projectId: number,
) =>
  request<ServiceAccount[]>(
    `/api/projects/${projectId}/service-accounts`,
  );

export const createServiceAccount = (
  projectId: number,
  name: string,
  scopes: string[],
  expiresAt?: string | null,
) =>
  request<ServiceAccountCredential>(
    `/api/projects/${projectId}/service-accounts`,
    {
      method: "POST",
      body: JSON.stringify({ name, scopes, expiresAt: expiresAt || null }),
    },
  );

export const revokeServiceAccount = (
  projectId: number,
  serviceAccountId: number,
) =>
  request<void>(
    `/api/projects/${projectId}/service-accounts/${serviceAccountId}`,
    { method: "DELETE" },
  );
