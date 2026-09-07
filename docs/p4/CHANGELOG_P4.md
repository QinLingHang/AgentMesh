# P4 change summary

## Python Runtime

- Added real built-in Tools: `calculator`, `current_time`, `text_stats`.
- Added sandboxed arithmetic parsing; no `eval`/`exec`.
- Added lightweight Tool input-schema validation before adapter execution.
- Added transient Tool retry for `timeout` / `unavailable` with trace events.
- Added local Streamable HTTP MCP demo server.
- Added local HTTP JSON POST Tool demo server.
- Added deterministic mock-provider routing for the new Tools/MCP demos.
- Added in-process MCP target injection for full Runtime integration tests.
- Hardened Tool trace redaction for credential / OTP / token-like values.

## Go Control Plane

- `seed-demo` now ensures the complete built-in Tool catalog even when old demo Tools already exist.
- Local demo MCP endpoint is configurable via `MCP_DEMO_ENDPOINT`.
- Existing `AgentMesh Demo MCP` records are refreshed to the configured endpoint when seeded again, fixing old `host.docker.internal` local-development records.

## React

- Extensions / Tools supports registering real HTTP JSON POST Tools.
- Extensions / MCP documents the real local MCP startup command.
- Run Details adds a dedicated `Tool & MCP` observability tab that shows execution metadata without expanding full business results.

## Architecture unchanged

- Memory remains User-global.
- Project Knowledge remains strictly Project-scoped.
- Project Runtime continues to filter Agent / Tool / MCP pools before Python execution.
