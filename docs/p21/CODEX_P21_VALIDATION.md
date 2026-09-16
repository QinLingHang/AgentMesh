# Codex P21 Validation Contract — FIX1 Re-acceptance

Validate production behavior; do not patch production files merely to satisfy the checks.

## QA model prerequisite (do not block on an external LLM)

The first acceptance was blocked because the QA user had no enabled model service. For this re-run, create a QA-only model service through the existing authenticated `/me/model-services` contract before submitting a real durable task:

- `provider`: `mock`
- `baseUrl`: any syntactically valid public HTTPS URL such as `https://example.invalid/v1`
- `modelName`: `agentmesh-qa-mock`
- `apiKey`: a non-empty **synthetic QA-only** value
- `enabled`: true
- `autoRoute`: true
- `isDefault`: true

Do not insert plaintext keys directly into MySQL. Use the product API so normal encryption/governance code is exercised. The Runtime mock provider is deterministic and performs no external model call. Remove only the QA user's model-service record during cleanup if safe.

## Static / unit gates

- Python compileall succeeds.
- `tests/test_p21_kafka_result_transport.py` passes, including producer success/failure counters.
- Existing P8 and V3 distributed Runtime tests pass in HTTP compatibility mode.
- Go `internal/eventbus` test proves DLQ cannot retain a synthetic secret or original Kafka key.
- P10 health contract test compiles with the P21 event-plane status argument.
- Go tests compile and pass after dependency resolution.
- `docker compose config` and production compose config are valid.

## Real-stack gates

Bring up MySQL, Redis, Kafka, Milvus, Go, Python Runtime, and the public gateway. Use `RUNTIME_RESULT_TRANSPORT=kafka` and `KAFKA_ENABLED=true`.

1. Submit a real durable Runtime task using the QA mock model service and prove the task completes with its assistant result persisted.
2. Prove `processed_runtime_events` contains the consumed `eventId` and Kafka offset metadata.
3. Replay the same Kafka event and prove no second assistant message / usage side effect is produced.
4. Publish a stale `fenceEpoch` event against a live/current assignment and prove it cannot overwrite the current assignment/result; `/health.eventPlane.staleFenceRejects` must increase.
5. Stop Go, complete a Runtime execution, restart Go, and prove the Kafka event is consumed after recovery.
6. Stop Kafka before a Runtime execution completes. Prove the result remains in `runtime_result_outbox.sqlite3`. Python health must show pending outbox and `produceFailed > 0`. Restart Kafka and prove eventual completion; `produced` must increase and the outbox row must disappear only after broker acknowledgement.
7. Kill/restart the Runtime process while a result is pending, retaining the outbox volume. Prove the same stable event is delivered after restart without re-running the Agent.
8. **Offset-skip regression:** cause the first fetched event on one partition to hit a temporary business-processing failure, then place a later valid event on that same partition. Prove the later offset is not fetched/committed past the unresolved earlier event. After recovery, both events must be handled in order or the first must be DLQ'd before the later offset is committed.
9. **Consumer crash replay:** crash/restart Go after the callback has entered `COMPLETING` but before the runtime-job completion marker is persisted. Prove replay resumes the same callback, does not create a duplicate assistant message, and eventually closes the Runtime Job. `callbackRecoveries` should provide evidence when the task/history transaction had already committed.
10. Publish malformed/unsupported event data containing a synthetic secret in both message key and payload. Prove it is routed to `agentmesh.runtime.events.dlq`, then read the DLQ record and verify:
    - synthetic secret absent from DLQ key and value,
    - no `payloadBase64`, raw payload, or raw source key,
    - `payloadSha256`, `keySha256`, `payloadBytes`, source topic/partition/offset and failure category are present,
    - subsequent valid events continue processing.
11. Run P8/V3/full regression suites and browser/canonical gates relevant to the current release.
12. Security scan: event/DLQ logs must not print prompt text, API keys, secrets, raw exception/provider content, or reversible source payload data.

Environment-only failures such as inability to reach Docker Hub / PyPI / proxy.golang.org must be reported separately from production-code defects.


## FIX2 mandatory re-validation

Before fault injection, verify a real durable task reaches `COMPLETED` using a QA model service created through the product API with `provider=mock`. The Python Runtime must not make an external model HTTP request for that service. While the task is active, Runtime `/health.heartbeat.sent` must increase and Go topology must keep the worker ONLINE. A heartbeat transport failure must increment `/health.heartbeat.failed` without exposing raw exception text or credentials. After the happy path succeeds, rerun the previously blocked Kafka outage, Python restart, Go consumer restart, duplicate-success-event, full stale-fencing competition, HTTP fallback, and COMPLETING crash-replay gates.

## FIX3 — Mandatory focused re-acceptance for Claude Code / Codex

Previous FIX2 final fault injection was **NOT PASS**: DEFECT-1 Kafka outage task failed despite delivered event (2/2), DEFECT-2 higher fence was swallowed by the same worker, DEFECT-3 default Go build/module download failed. Previous FIX2 COMPLETING crash replay had real proof (21/21); do not unnecessarily repeat an expensive 21-run campaign unless a regression appears. QA may start/stop services and write disposable QA-only scripts, but must not edit production code or clear shared MySQL/Redis/Kafka data.

1. **Start with clean reproducibility**: use a pristine FIX3 extraction in a separate QA directory, clear *only disposable QA module caches if safe*, run `go mod download`, `go build ./cmd/server`, `go test ./internal/runtime ./internal/eventbus`, and Docker build using `backend-go/Dockerfile` if the required image is locally available. Do not add `-mod=mod` or edit go.mod/go.sum to make it pass. Any external registry/DNS block is ENVIRONMENT BLOCK, not PASS.
2. **Targeted Python**: `pytest -q tests/test_p21_fix3_reliability.py tests/test_p21_kafka_result_transport.py tests/test_v3_distributed_runtime.py`; validate actual schema and dependencies rather than replacing application modules with test doubles in the final QA environment.
3. **Targeted Go DB**: use an isolated, writable P8 test DSN to run `TestP21ResultPendingHeartbeatSurvivesBrokerDelay`. Never use the development database for an integration-test fixture. If no isolated DSN exists, mark that gate SKIPPED/BLOCKED and rely on actual real-stack checks for dynamic coverage.
4. **DEFECT-1 B + B2**: stop Kafka during result production in two separate real mock-model tasks. Record pending SQLite `event_id`, observe job transition to `RESULT_PENDING` after outbox persistence, heartbeat/lease state and current Kafka consumer offsets. Restore Kafka and require both `tasks=COMPLETED` and `runtime_jobs=COMPLETED` for the same executions, without re-running Agent; verify exactly one result/assistant side effect. Include a broker-ACK-before-consumer-ACK interval and verify Python keeps the execution active until Go business ACK.
5. **DEFECT-2 F**: dispatch an execution at fence N to one Python worker, safely create a higher-fence N+1 assignment through the normal lease-recovery path onto **that same worker**; demand a new non-duplicate 202 and actual second runner invocation. Verify the N callback is stale and cannot overwrite N+1. Same-ownership redelivery is a valid duplicate; conflicting same-fence ownership must be rejected; no attempt silently consumed.
6. **OBSERVATION-3/4**: hold a legitimate callback in `COMPLETING` longer than 30 seconds while the task has committed. Require the reaper not to set the job FAILED; release or crash/replay and verify `task=COMPLETED`, `job=COMPLETED`, and no duplicated feedback/history. For Go restart, verify no premature accepted-worker-loss failure before heartbeat reconnect or Kafka replay; capture timing evidence rather than assuming 40 seconds always suffices.
7. **Quick regressions**: successful duplicate message, DLQ privacy, offset-skip, heartbeat, HTTP fallback, and G crash replay as necessary for the touched paths. Check `RESULT_PENDING` aged monitoring; do not claim final fault tolerance if a result can remain pending indefinitely with no alert/runbook.

Report `Production Defects`, `Test Defects`, `Environment Blocks`, `Source Modified By QA`, and per-scenario evidence separately. FINAL PASS requires defects=0 and all original hard real-stack gates; a successful Python unit suite alone is not sufficient.
