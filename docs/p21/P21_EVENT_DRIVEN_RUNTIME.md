# P21 Event-Driven Runtime & Kafka Reliability

## Goal

P21 adds a Kafka event plane without replacing the existing HTTP command plane or the MySQL-backed Durable Runtime scheduler. The first production event is `runtime.execution.result`, which replaces the fragile in-memory-only HTTP result callback when `RUNTIME_RESULT_TRANSPORT=kafka`.

## Reliability path

```text
Python Runtime execution finishes
  -> SQLite durable outbox (worker-local persistent volume)
  -> idempotent Kafka producer, acks=all
  -> agentmesh.runtime.events (key = execution_id)
  -> Go consumer group
  -> event_id dedupe ledger in MySQL
  -> existing DurableRuntimeService.Callback()
  -> fencing / lease validation
  -> task + assistant result persistence
  -> explicit Kafka offset commit
```

The legacy HTTP callback remains available with `RUNTIME_RESULT_TRANSPORT=http` for compatibility and rollback.

## Event envelope v1

```json
{
  "eventId": "stable UUID",
  "eventType": "runtime.execution.result",
  "eventVersion": 1,
  "occurredAt": "2026-09-16T00:00:00Z",
  "source": "runtime-python",
  "partitionKey": "execution-id",
  "userId": 1,
  "conversationId": 2,
  "executionId": "execution-id",
  "payload": {
    "jobId": 42,
    "callback": {
      "workerId": "runtime-node-a-worker-1",
      "executionId": "execution-id",
      "leaseToken": "...",
      "fenceEpoch": 3,
      "dispatcherEpoch": 7,
      "status": "completed",
      "response": {}
    }
  }
}
```

## Delivery semantics

P21 deliberately uses **at-least-once delivery + idempotent business handling** rather than claiming transport-level exactly-once semantics.

- A stable `eventId` is derived from execution id + fence epoch + terminal status.
- Kafka producer uses idempotence and `acks=all`.
- Worker writes the event to SQLite before attempting Kafka delivery.
- Go records processed event ids in `processed_runtime_events`.
- Existing Runtime fencing still rejects a stale worker result.
- Kafka offsets are committed only after business processing succeeds, or after an unprocessable event has been written to the DLQ.

## Topics

- `agentmesh.runtime.events` — Runtime lifecycle/result event stream. P21 production integration currently consumes `runtime.execution.result` v1.
- `agentmesh.runtime.events.dlq` — poison/terminal processing failures.

Future phases can add tool/model/audit/usage event topics without changing the command-plane API.

## Local development

Start infrastructure:

```bash
docker compose up -d mysql redis kafka etcd minio milvus
```

For the Go control plane:

```env
KAFKA_ENABLED=true
KAFKA_BROKERS=127.0.0.1:29092
```

For the Python Runtime:

```env
RUNTIME_RESULT_TRANSPORT=kafka
KAFKA_BROKERS=127.0.0.1:29092
KAFKA_OUTBOX_PATH=./data/runtime_result_outbox.sqlite3
```

Production Compose enables Kafka result transport by default and mounts a persistent Runtime outbox volume.

## Acceptance gates

1. Normal execution reaches COMPLETED through Kafka.
2. Duplicate event id does not duplicate business side effects.
3. Same execution is partition-keyed consistently.
4. Stale fence epoch is ignored safely.
5. Go consumer restart replays uncommitted messages safely.
6. Kafka outage leaves the result in the Runtime SQLite outbox.
7. Runtime restart resumes outbox delivery when the outbox volume is retained.
8. Invalid/poison events eventually land in the DLQ and do not permanently block the partition.
9. HTTP compatibility mode still passes P8/V3 tests.
10. Full Go/Python/React regressions remain green.
