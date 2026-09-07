# AgentMesh V3 Distributed Runtime Architecture

AgentMesh V3 extends the P8 durable runtime into a multi-node execution plane with capacity-aware scheduling, cross-node fencing and dispatcher high availability.

## Goals

- Multiple Python Runtime workers can register from multiple nodes.
- One logical durable queue is shared by all workers through MySQL.
- Control-plane replicas coordinate dispatcher ownership using a database lease.
- Scheduling uses authoritative durable-job state, not worker-reported active counters alone.
- Worker and node capacity are both enforced.
- Accepted executions are protected by lease token + monotonic fence epoch.
- Safe worker-loss replay is opt-in through `retryOnWorkerLoss`.
- Ambiguous post-accept execution is fail-closed by default.
- Node/worker/queue/dispatcher metadata is observable without exposing internal endpoints or secrets.

## Topology

```text
                         MySQL durable state
                                │
                 ┌──────────────┴──────────────┐
                 │                             │
          Control Plane A               Control Plane B
          Dispatcher A                  Dispatcher B
                 │                             │
                 └──── DB dispatcher lease ────┘
                                │
                         Durable Queue
                                │
                   Capacity-aware scheduler
                                │
          ┌─────────────────────┼─────────────────────┐
          │                     │                     │
       Node A                Node B                Node C
     Worker A1/A2          Worker B1              Worker C1/C2
```

Only the holder of the authoritative dispatcher lease dispatches work. The lease epoch increases when ownership transfers to another control-plane instance.

## Scheduling

Worker selection is ordered by a scheduling score composed from:

- authoritative active jobs on the worker;
- authoritative active jobs on the node;
- worker capacity;
- effective node capacity;
- recent dispatch failures/circuit-breaker state;
- last assignment time for fairness.

Worker heartbeat `activeExecutions` is telemetry. Durable `runtime_jobs` states are authoritative for reservation and capacity decisions.

V3 enforces both:

```text
worker authoritative active < worker capacity
node authoritative active   < node effective capacity
```

The node effective capacity is bounded by the declared node capacity and the sum of active worker capacities. This prevents two worker processes on one machine from independently over-allocating the same node.

## Lease and fencing

A job assignment carries:

- `executionId`
- random `leaseToken`
- monotonic `fenceEpoch`
- `dispatcherEpoch`
- `workerId`
- `nodeId`

Every reassignment increments `fenceEpoch`. A callback carrying an older non-zero fence epoch is ignored before completion side effects.

The worker heartbeat renews only an exact:

```text
jobId + executionId + workerId + leaseToken + fenceEpoch
```

tuple.

## Worker-loss recovery

Before worker acceptance, expired `LEASED` jobs can safely return to `QUEUED`.

After acceptance, replay is ambiguous unless the task explicitly opts in:

```json
{
  "retryOnWorkerLoss": true
}
```

If enabled and retry/deadline limits allow it, an expired accepted execution can be requeued and assigned to another node. Otherwise V3 fails closed.

## Dispatcher HA

`runtime_dispatcher_leases` stores one authoritative dispatcher holder.

- same holder renews the current epoch;
- a standby cannot dispatch while the lease is valid;
- after expiry, another holder takes over;
- takeover increments the epoch;
- the old holder cannot reclaim an unexpired new lease.

This provides HA for durable scheduling without requiring in-memory leader state.

## Privacy boundary

Browser APIs expose only sanitized topology metadata:

- worker/node IDs;
- status;
- zone/version;
- capacities;
- authoritative load;
- scheduling score;
- dispatcher epoch and lease health.

They do not serialize worker endpoints, internal tokens, lease tokens, BYOK secrets or runtime request bodies.
