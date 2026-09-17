# Distributed Runtime Observability

## Control-plane APIs

Authenticated browser clients can read:

```text
GET /api/runtime/reliability
GET /api/runtime/topology
```

The topology response combines queue/reliability metadata with sanitized node and worker views.

## Reliability metrics

The distributed runtime exposes:

- queued jobs;
- leased/dispatching jobs;
- accepted/completing jobs;
- failed/canceled jobs;
- worker count / available workers;
- draining workers;
- circuit-open workers;
- node count / available nodes / stale nodes;
- total effective capacity;
- authoritative active executions;
- utilization percentage;
- oldest queued age;
- dispatcher epoch;
- dispatcher lease remaining time;
- whether the current control-plane instance owns the dispatcher lease.

## Run trace

Durable completion prepends reliability metadata containing assignment identity such as:

- worker ID;
- node ID;
- fence epoch;
- dispatcher epoch;
- attempt count;
- failover-safe policy.

Secrets and worker endpoints are excluded.

## UI

The Tasks page adds a collapsible `Distributed Runtime` overview showing:

- online nodes;
- worker availability;
- capacity/utilization;
- queue depth;
- dispatcher leadership/epoch;
- per-node load;
- per-worker authoritative load and scheduling score.

Detailed per-run fencing metadata remains in Run Details rather than cluttering the Workspace.
