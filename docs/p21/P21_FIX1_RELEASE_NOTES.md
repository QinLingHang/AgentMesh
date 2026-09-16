# P21 FIX1 — Kafka Reliability & DLQ Privacy Closure

This fix is based on the first real-stack P21 acceptance report.

## Production fixes

1. **Privacy-safe DLQ**
   - Removed reversible `payloadBase64` storage.
   - The original Kafka message key is no longer forwarded to the DLQ.
   - DLQ records now contain only Kafka coordinates, byte length, failure category, and SHA-256 fingerprints of the source key/payload.
   - Raw malformed payloads, prompts, credentials, provider data, and arbitrary attacker-controlled bytes cannot be recovered from the DLQ record.

2. **No offset skip after transient processing failure**
   - A fetched message is now fully resolved before the consumer calls `FetchMessage` again.
   - Transient errors retry the exact same message in-place up to `KAFKA_PROCESS_MAX_ATTEMPTS`.
   - After retry exhaustion, the consumer remains on that exact record until its privacy-safe DLQ write succeeds.
   - This prevents a later successful message from committing a higher offset past an unresolved earlier message.

3. **Consumer crash / COMPLETING recovery**
   - Added callback ownership validation for jobs already in `COMPLETING`.
   - The same execution/worker/lease can resume callback finalization after a consumer restart.
   - If task/history finalization committed before the crash, replay only closes the Runtime Job marker and does not write the assistant result again.
   - Stale workers remain fenced out.

4. **P21 observability closure**
   - Python result transport health now exposes `outboxEnqueued`, `produced`, and `produceFailed`.
   - Go event-plane health now exposes `processingFailures`, `dlqPublishFailures`, `staleFenceRejects`, `callbackNoops`, and `callbackRecoveries` in addition to existing fetched/processed/duplicates/retries/DLQ counters.

## QA regression fixes

- Updated the V3 heartbeat test so it patches the public `httpx.AsyncClient` object rather than a fragile module attribute path.
- Updated the P10 health test for the P21 `eventPlaneStatus` route argument.
- Added a Go DLQ privacy unit test and Python producer-observability regression coverage.

## Real-stack retest requirement

P21 remains open until Codex re-runs the full real-stack acceptance. A deterministic QA model service can be created through the existing model-service API using provider `mock`, any syntactically valid public HTTPS base URL, a non-empty synthetic QA API key, and an enabled/default model. The Python Runtime's mock provider does not make an external model request; this removes the previous model-provider environment block without weakening the production model-selection path.
