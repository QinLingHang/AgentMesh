from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Protocol
from uuid import NAMESPACE_URL, uuid5

import httpx


@dataclass(frozen=True)
class ResultDelivery:
    job_id: int
    execution_id: str
    lease_token: str
    fence_epoch: int
    dispatcher_epoch: int
    worker_id: str
    callback_url: str
    status: str
    payload: dict[str, object]
    user_id: int | None = None
    conversation_id: int | None = None
    # Acknowledges only the local, committed SQLite outbox INSERT. This is
    # deliberately not a Kafka ACK or a final business acknowledgement.
    on_persisted: Callable[[], Awaitable[None]] | None = None


class ResultTransport(Protocol):
    async def start(self) -> None: ...
    async def publish(self, delivery: ResultDelivery) -> None: ...
    async def stop(self) -> None: ...


class HttpResultTransport:
    def __init__(self, *, internal_token: str, timeout_seconds: float, max_retries: int) -> None:
        self._internal_token = internal_token
        self._timeout_seconds = max(1.0, float(timeout_seconds))
        self._max_retries = max(1, int(max_retries))

    async def start(self) -> None:
        return

    async def stop(self) -> None:
        return

    def status(self) -> dict[str, object]:
        return {"mode": "http", "durable": False}

    async def publish(self, delivery: ResultDelivery) -> None:
        headers = {
            "X-Internal-Token": self._internal_token,
            "Content-Type": "application/json",
        }
        timeout = httpx.Timeout(self._timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            last_error: Exception | None = None
            for attempt in range(self._max_retries):
                try:
                    response = await client.post(
                        delivery.callback_url,
                        json=delivery.payload,
                        headers=headers,
                    )
                    if 200 <= response.status_code < 300:
                        return
                    if response.status_code < 500 and response.status_code not in (408, 429):
                        raise RuntimeError(f"callback rejected with HTTP {response.status_code}")
                except Exception as exc:  # noqa: BLE001 - transport boundary
                    last_error = exc
                if attempt + 1 < self._max_retries:
                    await asyncio.sleep(min(0.25 * (2**attempt), 2.0))
            # Compatibility mode preserves the P8 behavior: callback transport
            # exhaustion must not reclassify a successful Agent execution as a
            # Runtime failure. Kafka mode is the production path that provides
            # durable eventual delivery.
            return


class DurableKafkaResultTransport:
    """Durable Runtime result transport.

    Results are first persisted into a local SQLite outbox, then published to
    Kafka by a background loop. This closes the producer-side reliability gap:
    a short Kafka/network outage does not discard an already-completed Agent
    result, and a worker restart can resume publishing from the same outbox file.
    """

    def __init__(
        self,
        *,
        brokers: list[str],
        topic: str,
        client_id: str,
        outbox_path: str,
        publish_timeout_seconds: float = 10.0,
        retry_min_seconds: float = 0.5,
        retry_max_seconds: float = 15.0,
    ) -> None:
        self._brokers = [item.strip() for item in brokers if item.strip()]
        self._topic = topic.strip()
        self._client_id = client_id.strip() or "agentmesh-runtime"
        self._outbox_path = Path(outbox_path).expanduser().resolve()
        self._publish_timeout_seconds = max(1.0, float(publish_timeout_seconds))
        self._retry_min_seconds = max(0.1, float(retry_min_seconds))
        self._retry_max_seconds = max(self._retry_min_seconds, float(retry_max_seconds))
        self._producer: Any = None
        self._publisher_task: asyncio.Task[None] | None = None
        self._wake = asyncio.Event()
        self._stopping = False
        self._waiters: dict[str, asyncio.Future[None]] = {}
        self._outbox_enqueued = 0
        self._produced = 0
        self._produce_failed = 0

    async def start(self) -> None:
        self._initialize_outbox()
        if self._publisher_task is None:
            self._stopping = False
            self._publisher_task = asyncio.create_task(
                self._publisher_loop(),
                name="agentmesh-kafka-result-publisher",
            )

    async def stop(self) -> None:
        self._stopping = True
        self._wake.set()
        task = self._publisher_task
        self._publisher_task = None
        if task is not None:
            try:
                await asyncio.wait_for(task, timeout=5.0)
            except asyncio.TimeoutError:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        await self._close_producer()

    async def publish(self, delivery: ResultDelivery) -> None:
        event = self._build_event(delivery)
        encoded = json.dumps(event, ensure_ascii=False, separators=(",", ":"), default=str)
        event_id = str(event["eventId"])
        inserted = self._insert_outbox(
            event_id=event_id,
            partition_key=delivery.execution_id,
            payload_json=encoded,
        )
        if inserted:
            self._outbox_enqueued += 1
        if delivery.on_persisted is not None:
            # Outbox is already durable. A control-plane outage must NOT
            # prevent the publisher from eventually reaching Kafka.
            try:
                await delivery.on_persisted()
            except Exception:
                pass
        waiter = self._waiters.get(event_id)
        if waiter is None or waiter.done():
            waiter = asyncio.get_running_loop().create_future()
            self._waiters[event_id] = waiter
        self._wake.set()
        # Keep the execution record active (and its lease heartbeat renewable)
        # until Kafka durably acknowledges this event. A process crash is still
        # safe because the SQLite outbox survives and fencing rejects stale work.
        await asyncio.shield(waiter)

    def status(self) -> dict[str, object]:
        pending = 0
        if self._outbox_path.exists():
            try:
                with sqlite3.connect(self._outbox_path) as conn:
                    pending = int(
                        conn.execute("SELECT COUNT(*) FROM kafka_result_outbox").fetchone()[0]
                    )
            except sqlite3.Error:
                pending = -1
        return {
            "mode": "kafka",
            "durable": True,
            "topic": self._topic,
            "pendingOutbox": pending,
            "brokerConnected": self._producer is not None,
            "outboxEnqueued": self._outbox_enqueued,
            "produced": self._produced,
            "produceFailed": self._produce_failed,
        }

    def _initialize_outbox(self) -> None:
        self._outbox_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._outbox_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS kafka_result_outbox (
                    event_id TEXT PRIMARY KEY,
                    partition_key TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at REAL NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_kafka_result_outbox_next_attempt "
                "ON kafka_result_outbox(next_attempt_at, created_at)"
            )
            conn.commit()

    def _insert_outbox(self, *, event_id: str, partition_key: str, payload_json: str) -> bool:
        now = time.time()
        with sqlite3.connect(self._outbox_path) as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO kafka_result_outbox(
                    event_id, partition_key, payload_json, attempt_count,
                    next_attempt_at, created_at, updated_at
                ) VALUES(?, ?, ?, 0, 0, ?, ?)
                """,
                (event_id, partition_key, payload_json, now, now),
            )
            conn.commit()
            return cursor.rowcount == 1

    def _next_row(self) -> tuple[str, str, str, int] | None:
        with sqlite3.connect(self._outbox_path) as conn:
            row = conn.execute(
                """
                SELECT event_id, partition_key, payload_json, attempt_count
                FROM kafka_result_outbox
                WHERE next_attempt_at <= ?
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (time.time(),),
            ).fetchone()
        if row is None:
            return None
        return str(row[0]), str(row[1]), str(row[2]), int(row[3])

    def _delete_row(self, event_id: str) -> None:
        with sqlite3.connect(self._outbox_path) as conn:
            conn.execute("DELETE FROM kafka_result_outbox WHERE event_id = ?", (event_id,))
            conn.commit()

    def _reschedule_row(self, event_id: str, attempt_count: int) -> None:
        next_attempt = attempt_count + 1
        delay = min(self._retry_min_seconds * (2 ** min(next_attempt - 1, 8)), self._retry_max_seconds)
        now = time.time()
        with sqlite3.connect(self._outbox_path) as conn:
            conn.execute(
                """
                UPDATE kafka_result_outbox
                SET attempt_count = ?, next_attempt_at = ?, updated_at = ?
                WHERE event_id = ?
                """,
                (next_attempt, now + delay, now, event_id),
            )
            conn.commit()

    async def _publisher_loop(self) -> None:
        while True:
            row = self._next_row()
            if row is None:
                if self._stopping:
                    return
                self._wake.clear()
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=1.0)
                except asyncio.TimeoutError:
                    pass
                continue

            event_id, partition_key, payload_json, attempts = row
            try:
                producer = await self._ensure_producer()
                await asyncio.wait_for(
                    producer.send_and_wait(
                        self._topic,
                        payload_json.encode("utf-8"),
                        key=partition_key.encode("utf-8"),
                    ),
                    timeout=self._publish_timeout_seconds,
                )
                self._delete_row(event_id)
                self._produced += 1
                waiter = self._waiters.pop(event_id, None)
                if waiter is not None and not waiter.done():
                    waiter.set_result(None)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - retry is the contract here
                self._produce_failed += 1
                self._reschedule_row(event_id, attempts)
                await self._close_producer()
                if self._stopping:
                    return
                await asyncio.sleep(min(self._retry_min_seconds * (2 ** min(attempts, 5)), self._retry_max_seconds))

    async def _ensure_producer(self):
        if self._producer is not None:
            return self._producer
        if not self._brokers or not self._topic:
            raise RuntimeError("Kafka brokers/topic are not configured")
        try:
            from aiokafka import AIOKafkaProducer
        except ImportError as exc:
            raise RuntimeError("aiokafka is required for RUNTIME_RESULT_TRANSPORT=kafka") from exc

        producer = AIOKafkaProducer(
            bootstrap_servers=self._brokers,
            client_id=self._client_id,
            acks="all",
            enable_idempotence=True,
            compression_type="gzip",
            request_timeout_ms=int(self._publish_timeout_seconds * 1000),
            max_batch_size=1024 * 1024,
        )
        await producer.start()
        self._producer = producer
        return producer

    async def _close_producer(self) -> None:
        producer = self._producer
        self._producer = None
        if producer is not None:
            try:
                await producer.stop()
            except Exception:
                pass

    def _build_event(self, delivery: ResultDelivery) -> dict[str, object]:
        identity = (
            f"agentmesh://runtime-result/{delivery.execution_id}/"
            f"{delivery.fence_epoch}/{delivery.status}"
        )
        event_id = str(uuid5(NAMESPACE_URL, identity))
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        return {
            "eventId": event_id,
            "eventType": "runtime.execution.result",
            "eventVersion": 1,
            "occurredAt": now,
            "source": "runtime-python",
            "partitionKey": delivery.execution_id,
            "userId": delivery.user_id,
            "conversationId": delivery.conversation_id,
            "executionId": delivery.execution_id,
            "payload": {
                "jobId": delivery.job_id,
                "callback": delivery.payload,
            },
        }


def build_result_transport(
    *,
    mode: str,
    internal_token: str,
    callback_timeout_seconds: float,
    callback_max_retries: int,
    kafka_brokers: str,
    kafka_topic: str,
    kafka_client_id: str,
    kafka_outbox_path: str,
    kafka_publish_timeout_seconds: float,
) -> ResultTransport:
    normalized = mode.strip().lower()
    if normalized == "http":
        return HttpResultTransport(
            internal_token=internal_token,
            timeout_seconds=callback_timeout_seconds,
            max_retries=callback_max_retries,
        )
    if normalized == "kafka":
        return DurableKafkaResultTransport(
            brokers=[item for item in kafka_brokers.split(",") if item.strip()],
            topic=kafka_topic,
            client_id=kafka_client_id,
            outbox_path=kafka_outbox_path,
            publish_timeout_seconds=kafka_publish_timeout_seconds,
        )
    raise ValueError("RUNTIME_RESULT_TRANSPORT must be 'http' or 'kafka'")
