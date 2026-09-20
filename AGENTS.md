# AGENTS.md

## What this repo is

AgentMesh — a multi-tenant Agent application & runtime platform, built as a polyglot monorepo:

| Directory | Role |
|:---|:---|
| `backend-go/` | Go/Gin Control Plane: auth, orgs/workspaces, RBAC, agent/tool registry, durable task queue, Kafka result consumer, MySQL persistence. Module path: `example.com/agentmesh-control-plane`. Entry: `cmd/server` (default port `8086` via `BUSINESS_PORT`). |
| `runtime-python/` | Python/FastAPI Agent Runtime: semantic planner, execution plan validation, adaptive scheduler, hybrid DAG executor, quality gate/repair/replan, RAG, memory, tools/MCP, model gateway. Entry: `uvicorn app.main:app`, port `9572`. |
| `web-react/` | React 19 + TypeScript + Vite frontend. Dev server port `5173`. |
| `desktop-bridge/` | Separate FastAPI service for read-only desktop capabilities (Windows-only deps: `pywinauto`, `pywin32`). |
| `sdk/python/`, `sdk/typescript/` | Client SDKs for the public API. |
| `infra/`, `scripts/` | Nginx gateway/MySQL init; PowerShell ops & smoke/e2e runner scripts. |
| `docs/` | Architecture + domain docs (runtime, platform, operations, governance, memory, multimodal, security, desktop). |

## Request chain & frozen architecture boundaries

`React → Go POST /api/tasks/run (JWT) → Go Runtime Client → Python POST /internal/v1/runtime/execute → plan/schedule/DAG → result via SQLite outbox → Kafka → Go consumer → MySQL`.

Do not blur these boundaries (see `docs/ARCHITECTURE.md`):

- Go = API/auth/governance/durable dispatch + persistence. Python = all agent intelligence (planning, routing, DAG, RAG, memory, tools). Web = product UI only.
- **Planner decides *what* to do; Scheduler decides *who* executes.** Planner output must go through plan validation before execution; never let the planner pick concrete agents.
- LangGraph is only one of four agent executors (Internal / LangGraph / HTTP / A2A). It owns no queue/lease/fencing/Kafka logic.
- Go durable queue = reliable task dispatch; Kafka = reliable result delivery. They are independent planes.
- Completed side-effect steps (Tool/HTTP/A2A actions) must never be auto-replayed for quality reasons (bounded repair/replan only, completed-step carry-forward).

Go↔Python auth: shared internal token — Go `RUNTIME_INTERNAL_TOKEN` must equal Python `INTERNAL_TOKEN`.

## Build & test commands

Run each suite from its own directory. `docs/TESTING.md` is the authoritative testing doc.

**Go** (`backend-go/`):
```
go test ./... -count=1
```
MySQL-backed integration tests skip unless these are set: `P2_TEST_MYSQL_DSN`, `P3_TEST_MYSQL_DSN` (same DSN), `P3_TEST_PYTHON`. Tests create/drop uniquely-named temp databases (they never use the DSN's own DB). **A skipped integration test must not be reported as PASS** — a missing DSN is an environment blocker.

**Python runtime** (`runtime-python/`, must cd there — `pytest.ini` sets `pythonpath = .`):
```
python -m pytest -q
```
Imports are always `app.*`. `tests/conftest.py` forces offline-safe defaults (`MODEL_PROVIDER=mock`, `RAG_BACKEND=inmemory`, `EMBEDDING_BACKEND=hash`, `RERANKER_BACKEND=heuristic`, `MEMORY_RETRIEVAL_ENABLED=false`) — unit tests must not require real models or Milvus/MySQL/Kafka. pytest asyncio mode is `auto`.

**Web** (`web-react/`):
```
npm test        # contract tests: node --test on tests/*.test.mjs (no vitest/jest)
npm run build   # tsc -b && vite build — the source of truth for TS correctness
```
A >500 kB chunk warning is a known backlog item, not a failure (exit 0 = pass). Browser e2e runners live in `e2e/` (`npm run test:e2e:v2|v3|v4`, etc.) and need the stack running.

**SDKs**: `sdk/python`: `python -m unittest discover -s tests`; `sdk/typescript`: `npm test` (builds first). Both use local fixtures, no model needed.

## Local environment

- Dev OS is **Windows**; PowerShell is used for ops/e2e scripts (`scripts/*.ps1`). Git Bash works for git/go/npm/python.
- Config: copy `backend-go/.env.example` and `runtime-python/.env.example` to `.env` (both are godotenv/pydantic-settings loaded).
- Infra via Docker Compose, project name `agentmesh_runtime_mvp_full_v02` (`docker compose -p agentmesh_runtime_mvp_full_v02 ps`): MySQL, Redis, Kafka, Milvus, etcd, MinIO. **Never run `docker compose down -v` against a dev environment with data.**
- Kafka result-delivery mode requires both sides enabled: Go runtime consumer + Python Kafka result transport.
- Adaptive workflow bounds (planner timeout/max steps, repair/replan attempts, quality-gate thresholds) are env-tunable in `runtime-python/.env`.

## Docs to read before touching sensitive areas

- `docs/TESTING.md` — test commands & pass/fail rules.
- `docs/ARCHITECTURE.md` — frozen boundary & request chain.
- `docs/runtime/EVENT_DRIVEN_RUNTIME.md` — outbox/Kafka/idempotency/fencing.
- `docs/runtime/DISTRIBUTED_RUNTIME.md`, `docs/operations/FAILOVER.md` — lease/fencing/HA.
- `docs/memory/` (esp. `MEMORY_BOUNDARY.md`, `WRITE_POLICY.md`) — memory is user-global, knowledge is project-scoped; never cross the two.
- `docs/governance/MULTI_TENANT.md`, `docs/security/TENANT_BOUNDARIES.md` — every resource (agent/tool/MCP/knowledge/model) is project-scoped; planner/replanner may not bypass registry/scheduler/governance.
