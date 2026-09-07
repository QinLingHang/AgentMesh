# P8 — Distributed Runtime + Resilience + Production Readiness

## 1. Goal

P8 turns the existing synchronous Go → Python execution call into an optional durable delivery plane without changing P1–P7 semantics. `direct` remains available for compatibility; `durable` is the default UI delivery mode.

```text
Browser
  │ POST /api/tasks/run-durable
  ▼
Go Control Plane
  │ atomic Task(QUEUED) + RuntimeJob(QUEUED)
  ▼
MySQL durable queue
  │ claim + lease + fencing token
  ▼
Dispatcher ── current Project Agent/Tool/MCP recheck
  │
  │ mark DISPATCHING before network send
  ▼
Python Runtime Worker
  │ 202 Accepted  ← acceptance boundary
  │ background Agent execution
  ▼
Authenticated callback
  │ executionId + workerId + leaseToken CAS
  ▼
Go persists Task / Message / Trace / Eval
```

## 2. Durable state machine

Runtime Job states:

```text
QUEUED
  ↓ claim
LEASED
  ↓ dispatch fence
DISPATCHING
  ↓ 202
ACCEPTED
  ↓ callback CAS
COMPLETING
  ↓
COMPLETED
```

Terminal alternatives: `FAILED`, `CANCELED`.

Only `LEASED` jobs whose lease expires are automatically recovered to `QUEUED`. A `DISPATCHING` or `ACCEPTED` job has crossed the network ambiguity boundary and is never automatically replayed.

## 3. Retry safety boundary

Automatic retry is allowed only when non-acceptance is provable:

- TCP dial/connect failure before a worker can accept the request;
- HTTP `429` / `503` explicitly carrying `X-AgentMesh-Accepted: false`.

Everything else is fail-closed. In particular, timeout/reset/5xx after dispatch may mean the worker accepted a side-effecting execution even when Go did not receive the acknowledgment. P8 prefers an explicit failed/ambiguous task over duplicate execution.

## 4. Lease and fencing

Each claim writes a random `lease_token`. Worker callbacks must match all of:

- Runtime Job ID;
- stable `execution_id`;
- worker ID;
- lease token.

`BeginRuntimeJobCallback` performs a compare-and-set from `DISPATCHING/ACCEPTED` to `COMPLETING`. Duplicate or stale callbacks cannot execute persistence side effects twice.

Worker capacity reservations are serialized by locking the worker row and counting durable in-flight job states. Heartbeat active counts remain telemetry and cannot cause two control-plane dispatchers to over-claim the same worker.

## 5. Worker idempotency

Python keeps a stable execution-ID dedupe record during the configured retention window. A repeated submission for an existing execution ID returns `202` with `duplicate=true` and reuses the original asyncio task.

This is a second line of defense, not a reason to retry ambiguous accepted executions.

## 6. Backpressure and circuit breaker

Control plane protection:

- global durable queue limit;
- per-worker capacity;
- stale/draining workers excluded from dispatch;
- consecutive pre-accept dispatch failures open a worker circuit;
- circuit-open workers are excluded until the open interval expires;
- deadline expiry converts unresolved post-dispatch work into an ambiguous failure rather than replay.

## 7. Governance boundary

The queued JSON freezes task/policy inputs but deliberately does **not** freeze Agent/Tool/MCP pools. Immediately before dispatch the Go control plane reloads the user's currently enabled resources and Project Runtime bindings, then filters the execution pool again.

Therefore a resource revoked while a task is waiting in the queue cannot be resurrected by an old queue payload.

## 8. Cancel and graceful shutdown

User cancellation CASes a user-owned `QUEUED/RUNNING` durable task to `CANCELED` and best-effort cancels the assigned worker execution when one exists.

Python shutdown:

1. mark worker draining;
2. send heartbeat;
3. stop accepting new executions;
4. wait for active tasks for a bounded grace period;
5. cancel remaining local tasks and callback `canceled`.

Go shutdown stops the dispatcher and uses `http.Server.Shutdown` with a bounded timeout.

## 9. Reliability observability/privacy

Public reliability snapshot contains counts only: queue depth, active durable states, worker counts, available/draining/circuit-open workers, oldest queued age. Worker network endpoints never appear in browser JSON.

Run Details `Reliability` events use a strict metadata whitelist: delivery mode, job/execution IDs, worker ID, attempt counters, dispatch status. Malformed trace detail fails closed and is never rendered as raw text.

## 10. Deployment

`docker-compose.production.yml` builds and connects:

- MySQL
- Redis
- etcd / MinIO / Milvus
- Go Control Plane
- Python Runtime Worker
- local MCP demo service
- React/Nginx UI

Copy `.env.production.example` to `.env.production`, replace all `CHANGE_ME` values, then validate/start with Docker Compose as documented in `P8_COMPLETION.md`.
