# Multi-node / HA Operations

The multi-node topology keeps the normal `docker-compose.production.yml` behaviour unchanged. Multi-node Runtime and control-plane HA are enabled only when the optional overlay is selected.

## Start the HA topology

```bash
docker compose \
  -f docker-compose.production.yml \
  -f docker-compose.v3-ha.yml \
  up -d --build
```

The overlay adds:

- `backend-go` / dispatcher-a
- `backend-go-b` / dispatcher-b
- `runtime-python` / node-a
- `runtime-python-b` / node-b
- API load balancing through the gateway

Both Go instances share MySQL, Redis and the same migration state. Only one durable dispatcher owns the database-backed dispatcher lease at a time.

## Inspect topology

From an authenticated browser/API session:

```text
GET /api/runtime/reliability
GET /api/runtime/topology
```

Expected healthy state includes two available nodes, two Runtime workers and one authoritative dispatcher holder.

## Worker drain

Use only from the trusted internal network:

```text
POST /internal/v1/runtime/worker/drain?draining=true
X-Internal-Token: <runtime internal token>
```

The worker rejects new durable work before acceptance but allows accepted work to finish.

## Dispatcher failover validation

1. Start both Go instances.
2. Confirm one instance reports `dispatcherLeader=true`.
3. Stop the current leader container.
4. Wait longer than `DURABLE_RUNTIME_DISPATCHER_LEASE_SECONDS`.
5. Confirm the standby becomes leader and `dispatcherEpoch` increases.
6. Submit a new durable task and confirm it is dispatched normally.

## Runtime node-loss validation

1. Start node-a and node-b.
2. Submit a task with `retryOnWorkerLoss=true` only when the workload is safe to replay.
3. After worker acceptance, stop the assigned Runtime node.
4. Wait for its execution lease to expire.
5. Confirm the job returns to `QUEUED`, is assigned to another node, and gets a larger fence epoch.
6. Send/observe any stale callback from the old assignment; it must not commit completion side effects.

For a task without `retryOnWorkerLoss`, the same accepted-worker-loss scenario must fail closed instead of replaying automatically.

## Request-plane HA boundary

The HA overlay load-balances `/api/` between both Go services. This covers stateless HTTP request-plane failover for the control plane. MySQL, Redis, Milvus and object storage are still single logical services in the default Compose topology; clustered database/storage HA remains part of the final cloud production closure rather than being falsely claimed by the local HA Compose topology.
