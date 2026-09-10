export type AgentMeshClientOptions = {
  baseUrl: string;
  apiKey: string;
  fetchImpl?: typeof fetch;
};

export type RunTaskInput = {
  task: string;
  conversationId?: number;
  scheduler?: string;
  planner?: string;
  executionMode?: string;
  synthesisMode?: string;
  constraints?: Record<string, unknown>;
};

export class AgentMeshError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code?: number,
    readonly data?: unknown,
  ) {
    super(message);
    this.name = "AgentMeshError";
  }
}

type Envelope<T> = { code: number; message?: string; data: T };

export class AgentMeshClient {
  private readonly baseUrl: string;
  private readonly apiKey: string;
  private readonly fetchImpl: typeof fetch;

  constructor(options: AgentMeshClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/+$/, "");
    this.apiKey = options.apiKey.trim();
    this.fetchImpl = options.fetchImpl ?? fetch;
    if (!this.baseUrl || !this.apiKey) throw new Error("baseUrl and apiKey are required");
  }

  private async request<T>(
    method: string,
    path: string,
    options: { body?: unknown; query?: Record<string, string | number | undefined>; idempotencyKey?: string } = {},
  ): Promise<T> {
    const url = new URL(this.baseUrl + path);
    for (const [key, value] of Object.entries(options.query ?? {})) {
      if (value !== undefined && value !== "") url.searchParams.set(key, String(value));
    }
    const headers: Record<string, string> = {
      Accept: "application/json",
      Authorization: `Bearer ${this.apiKey}`,
    };
    if (options.body !== undefined) headers["Content-Type"] = "application/json";
    if (options.idempotencyKey) headers["Idempotency-Key"] = options.idempotencyKey;
    const response = await this.fetchImpl(url, {
      method,
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });
    let payload: Envelope<T> | undefined;
    try {
      payload = (await response.json()) as Envelope<T>;
    } catch {
      throw new AgentMeshError(`invalid JSON response (${response.status})`, response.status);
    }
    if (!response.ok || payload.code !== 0) {
      throw new AgentMeshError(payload.message || `HTTP ${response.status}`, response.status, payload.code, payload.data);
    }
    return payload.data;
  }

  runTask(input: RunTaskInput, options: { idempotencyKey?: string } = {}) {
    return this.request<Record<string, unknown>>("POST", "/openapi/v1/tasks/run", {
      body: {
        scheduler: "adaptive",
        planner: "multi_objective",
        executionMode: "auto",
        synthesisMode: "auto",
        constraints: {},
        ...input,
      },
      idempotencyKey: options.idempotencyKey,
    });
  }

  getTask(taskId: number) {
    return this.request<Record<string, unknown>>("GET", `/openapi/v1/tasks/${taskId}`);
  }

  marketplace(options: { query?: string; kind?: string; limit?: number } = {}) {
    return this.request<Array<Record<string, unknown>>>("GET", "/openapi/v1/marketplace", {
      query: { q: options.query, kind: options.kind, limit: options.limit ?? 50 },
    });
  }

  package(slug: string) {
    return this.request<Record<string, unknown>>("GET", `/openapi/v1/marketplace/${encodeURIComponent(slug)}`);
  }
}
