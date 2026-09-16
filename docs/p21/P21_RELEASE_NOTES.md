# P21 Release Notes — Event-Driven Runtime & Kafka Reliability

## Production changes

- Added Kafka Event Plane while preserving HTTP/SSE command/query paths.
- Runtime result delivery supports `http` compatibility mode and `kafka` production mode.
- Kafka mode writes terminal Runtime results to a persistent SQLite outbox before broker delivery.
- Execution remains active until Kafka acknowledges the result, so lease heartbeats continue during transient broker/network outages.
- Added stable `eventId`, execution-id partition key, event versioning, and an explicit Runtime result event envelope.
- Added Go Kafka consumer group with manual offset commit, MySQL event-id dedupe ledger, existing lease/fence validation, bounded processing retry, and DLQ routing.
- Added P21 event-plane counters to Go `/health` and Runtime result-transport/outbox state to Python `/health`.
- Added dedupe-ledger retention cleanup.
- Local Compose includes single-node Kafka plus topic initialization.
- Production Compose includes a 3-node KRaft Kafka cluster, RF=3, min ISR=2, explicit topic initialization, and persistent broker volumes.
- HA Runtime overlay uses a separate persistent SQLite outbox volume for the second Runtime node.
- Pre-created topic families: runtime, tool, model, audit, usage, plus runtime DLQ.

## Compatibility

- Existing Durable Runtime scheduling, worker registration, heartbeat, lease, fencing, worker-loss recovery, deadline/cancel, governance checks, and HTTP dispatch remain intact.
- Existing HTTP callback behavior remains selectable with `RUNTIME_RESULT_TRANSPORT=http`.
- P21 changes the production result transport only when Kafka mode is enabled.

## Validation performed in this workspace

- Python application source: `compileall` PASS.
- P21 Kafka transport smoke with fake broker producer: PASS.
- Compose YAML parsing for local, production, and V3 HA files: PASS.
- Full Python pytest could not run because this execution environment does not have the pre-existing `mcp` dependency installed.
- Go tests could not resolve existing or new modules because outbound access to `proxy.golang.org` is blocked in this execution environment.
- Docker Compose runtime validation could not run because the Docker CLI is unavailable here.

Use `docs/p21/CODEX_P21_VALIDATION.md` for real-stack acceptance in the normal development environment.

## FIX1 closure after first real-stack acceptance

See `P21_FIX1_RELEASE_NOTES.md`. FIX1 removes reversible DLQ payload storage, prevents offset advancement past unresolved transient failures, makes `COMPLETING` callback replay recoverable after consumer crashes, closes the missing producer/stale-fence observability counters, and repairs the two stale QA tests identified by the first acceptance run.


## FIX2 — Heartbeat + deterministic mock model closure

- Restored the missing `httpx` import used by durable worker heartbeats.
- Heartbeat HTTP failures are now visible in Runtime `/health` through sent/failed counters and a redacted error category; non-2xx responses are treated as failed heartbeats.
- Request-local `provider=mock` model services now instantiate `MockModelProvider` directly instead of the OpenAI-compatible HTTP provider.
- Project fallback and image attachment request-local model resolution use the same mock semantics.
- Added regressions for heartbeat success/failure observability and deterministic request-local mock routing.
- FIX1 DLQ privacy and offset-skip behavior are unchanged.

## FIX3 — Fault-injection follow-up (not yet finally accepted)

See `P21_FIX3_RELEASE_NOTES.md` for the three FIX2 final fault-injection defects, corresponding production changes, operational limitations, and regression plan. P21 remains open until a normal-environment re-acceptance proves the Kafka-outage end-to-end terminal state, higher-fence handover on the same worker, and clean Go/Docker builds. Previously verified COMPLETING crash replay remains a regression gate, not an excuse to skip new defect tests.
