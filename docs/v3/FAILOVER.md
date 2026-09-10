# V3 Failover Semantics

## Failure classes

### Worker unavailable before acceptance

Connection failure or explicit `429/503` with `X-AgentMesh-Accepted: false` is considered pre-accept and retryable within the configured retry/deadline boundary.

### Ambiguous dispatch

If the control plane cannot prove that the worker did not accept the request, automatic replay remains disabled. This protects non-idempotent Agent/Tool actions from duplicate side effects.

### Accepted worker disappears

The Python worker renews the exact execution lease in heartbeat. If the lease expires:

- `retryOnWorkerLoss=false` → fail closed;
- `retryOnWorkerLoss=true` and attempts/deadline remain → requeue and increment fence on next claim.

### Stale callback

A callback with an old V3 `fenceEpoch` is ignored. The current assignment remains authoritative.

### Node loss

Workers and nodes whose heartbeat exceeds `DURABLE_RUNTIME_WORKER_STALE_SECONDS` become `OFFLINE`. Offline/draining/circuit-open workers are removed from scheduler candidates.

### Dispatcher loss

Standby control-plane instances poll the same database lease. After expiration one standby acquires the lease, increments the dispatcher epoch and continues dispatch/recovery work.

## Graceful maintenance

Python Runtime exposes the internal worker drain endpoint:

```text
POST /internal/v1/runtime/worker/drain?draining=true
X-Internal-Token: ...
```

Draining rejects new durable executions before acceptance while already accepted executions continue. Runtime shutdown also enters draining before waiting for the configured grace period.
