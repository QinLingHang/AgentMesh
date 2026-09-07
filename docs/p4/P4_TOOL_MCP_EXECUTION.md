# P4 — Tool + MCP Real Execution

P4 turns the existing Tool/MCP contracts into a locally runnable execution loop.

## Runtime path

```text
User task
  -> Go Control Plane
  -> account enabled resources
  -> Project Runtime filter
  -> Python task-scoped ToolRegistry
  -> model tool selection
  -> Tool governance
  -> schema validation
  -> execute internal / HTTP / MCP adapter
  -> transient retry
  -> tool observation back to model
  -> final answer
  -> Run Details / Tool & MCP
```

Project Runtime remains the resource scope boundary. A Tool or MCP server that is disabled or outside the current project binding never enters the Python request pool.

## Built-in tools

`POST /api/tools/seed-demo` is kept for backwards compatibility but now *ensures* the local built-in catalog instead of returning early when any Tool already exists.

Built-ins:

- `calculator` — sandboxed arithmetic parser; no Python eval/exec.
- `current_time` — IANA timezone date/time lookup.
- `text_stats` — deterministic text statistics.

Legacy deterministic integration tools (`get_order`, `get_logistics`, `diagnose_service`) remain available for regression and demos.

HTTP Tool registration is available from the Extensions / Tools panel. A local JSON POST demo server can be started from `runtime-python` with:

```powershell
.\.venv\Scripts\python.exe -m app.tools.http_demo_server
```

Default echo endpoint: `http://127.0.0.1:9584/tool/echo`.

## Tool safety

Before an adapter receives model arguments, Runtime checks:

- Tool enabled state and risk/approval policy.
- Arguments are a JSON object.
- Required fields.
- Declared primitive field types.
- `additionalProperties: false` when configured.

Transient `timeout` and `unavailable` failures are retried by the Tool Loop. Invalid arguments, permission denial and execution failures are not blindly retried.

## Local MCP server

From `runtime-python`:

```powershell
.\.venv\Scripts\python.exe -m app.mcp.demo_server
```

Default endpoint:

```text
http://127.0.0.1:9583/mcp
```

The Go seed endpoint uses `MCP_DEMO_ENDPOINT`, defaulting to the same local URL. Docker deployments can override it, for example with an internal service DNS name.

Demo MCP tools:

- `lookup_weather`
- `calculate_shipping_eta`
- `get_order_status`

## Observability

Run Details now contains a dedicated **Tool & MCP** tab. It shows execution metadata (tool/server, protocol/transport, status, latency, retries, discovery counts and error type) but intentionally does not expand full Tool results.

The complete low-level events remain in Trace with existing redaction rules.
