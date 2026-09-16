# P21 FIX3 — Kafka Business ACK, Fence-Safe Reassignment, Reproducible Go Modules

## Why this change is required

Claude Code's FIX2 final fault injection was **NOT PASS** with three production defects. It verified that the existing COMPLETING crash replay works (21/21), but Kafka-outage tasks failed after the publisher received a broker ACK, a higher-fence assignment could be silently discarded on the same Python worker, and clean Go builds could not resolve the delivered module metadata. This revision addresses those three causes. It does **not** claim final real-stack acceptance: the repair must be re-tested on the user's normal environment.

## FIX3 production changes

### DEFECT-1 — Kafka broker ACK is not a Go business ACK

- After the result is committed to the Python SQLite outbox, the worker sets `resultPending` in its heartbeat with the *exact* job ID, execution ID, worker ID, lease token, and fence epoch.
- Go persists `runtime_jobs.status=RESULT_PENDING` only for matching current ownership. The normal accepted-worker-loss and execution-deadline reapers do **not** fail this state just because a broker or consumer is temporarily unavailable. `RESULT_PENDING` continues to count toward capacity and is accepted by the existing callback/finalization path.
- Python keeps the task and execution lease alive after **broker** ACK. Go heartbeat explicitly returns `terminalExecutionIds` only when the same owned job is terminal; this is a separate **business** ACK. A generic HTTP 200 from the heartbeat is not treated as business completion.
- Following a Go restart, accepted-worker-loss reaping has a finite reconnect grace period (two times `WorkerStaleAfter`). The existing Kafka/outbox replay still works if Python exits: Go can consume the pending result even without a live worker heartbeat.
- For a stalled `COMPLETING` callback, stop applying the old 30-second deadline failure that could leave `tasks=COMPLETED` but `runtime_jobs=FAILED`. A throttled, conservative reconciliation can close a `COMPLETING` job older than ten minutes when its task already holds an authoritative successful terminal state; Kafka replay remains the preferred fast path.

Operational boundary: `RESULT_PENDING` intentionally does not get an automatic replay/failure from worker disappearance: the **durable result**, rather than re-executing an ambiguous Agent, is the source of truth. Operators must alert on old RESULT_PENDING entries, inspect Kafka/DLQ and preserved outbox volumes, and handle irrecoverable outbox/data loss explicitly. This is not a claim of mathematically guaranteed delivery if all persistent copies are destroyed.

### DEFECT-2 — Fence-aware duplicate acceptance

- Python deduplication now compares `(execution_id, fence_epoch, lease_token, job_id)`, not only `execution_id`.
- Identical current-ownership submission replies `duplicate=true` with the acknowledged `fenceEpoch`. A lower fence or conflicting same-fence ownership is explicitly rejected with HTTP 409. A higher fence creates a new execution task and supersedes/cancels the old in-memory attempt while preserving any already-persisted outbox result for Go to fence out.
- Go validates a worker's `duplicate=true` ACK against the requested fence and fails closed if it is mismatched/missing. The change does **not** allow replay of ambiguous accepted work without the platform's existing safe-retry policy.

### DEFECT-3 — Go module reproducibility

- Declare Kafka codec transitives `github.com/klauspost/compress v1.15.9` and `github.com/pierrec/lz4/v4 v4.1.15` as indirect modules in `backend-go/go.mod`, and include their published module and artifact checksums in `backend-go/go.sum`.
- This addresses the FIX2 report's default `go build` / `go mod download` missing-metadata issue. A clean default build and a Docker build **must still be run by QA**; this environment cannot fetch uncached modules from `proxy.golang.org` and has no Docker daemon.

## Regressions added

- `runtime-python/tests/test_p21_fix3_reliability.py`: same/future/stale fence semantics, broker ACK versus business ACK, and terminal heartbeat acknowledgement.
- `backend-go/internal/runtime/worker_client_p8_test.go`: mismatched and missing duplicate fence ACK fail closed.
- `backend-go/internal/service/p21_fix3_result_pending_integration_test.go`: DB-backed RESULT_PENDING ownership/renewal/worker-loss protection, callback transition, completion ACK, and no premature COMPLETING deadline failure. This uses the P8 **isolated test DSN** fixture; it must skip rather than touch a user's development DB if no safe test DSN exists.

FIX1 DLQ redaction and offset-skip changes, FIX2 heartbeat import and local MockModelProvider routing remain intact.

## Acceptance status

Repair packaged; **P21 FINAL PASS is not asserted**. Rerun targeted tests and three defects' dynamic reproductions before closing P21. In particular B/B2 must finish with `task=COMPLETED`, not merely `outbox.pending=0`.
