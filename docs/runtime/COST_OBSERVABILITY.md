# Cost and Observability

## Token usage

AgentMesh continues to consume provider-reported token usage when available:

- input tokens
- output tokens
- total tokens

The mock provider produces deterministic token usage for tests. Providers that do not report usage are not assigned fabricated precise values.

## Pricing semantics

`app.models.cost` centralizes model pricing and cost calculation.

Cost status is one of:

- `actual`
- `estimated`
- `unavailable`

Current model-provider pricing produces `estimated` cost when prices are configured. When prices are unknown (including BYOK with no configured price), usage remains visible but cost is `unavailable` rather than pretending the run cost is zero.

## Go persistence

The control plane persists run-level usage in `run_cost_records`.

It records:

- task/user/project identity
- provider/model
- input/output/total tokens
- estimated cost
- cost status

Repeated model phases for the same task accumulate into the run record. Telemetry persistence is best-effort and must not fail an otherwise completed task.

## Cost APIs

Authenticated APIs:

```text
GET /api/costs/summary
GET /api/projects/:id/costs
GET /api/tasks/:taskId/cost
```

Summary endpoints support optional RFC3339 `from` / `to` and `provider` / `model` filters.

Security rules:

- user summary is scoped to the authenticated user;
- project summary requires at least project VIEWER access and includes the complete authorized project, not only the current user's runs; unrelated users receive not-found semantics to preserve the existing project IDOR-hiding contract;
- run detail remains user-scoped;
- cost data never exposes BYOK plaintext.

## Runtime observability

The observability layer adds:

- model provider/model
- retrieval mode
- RAG latency
- raw/selected/context hit counts
- text/visual candidate counts
- tool success/failure counts
- token and estimated cost telemetry

React Run Details exposes these signals separately from the clean Workspace answer surface.
