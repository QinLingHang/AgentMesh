from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from app.distributed.result_transport import DurableKafkaResultTransport, ResultDelivery


class _FakeProducer:
    def __init__(self) -> None:
        self.messages: list[tuple[str, bytes, bytes | None]] = []

    async def send_and_wait(self, topic: str, value: bytes, *, key: bytes | None = None):
        self.messages.append((topic, value, key))
        return object()

    async def stop(self) -> None:
        return


@pytest.mark.asyncio
async def test_kafka_result_transport_persists_then_publishes(tmp_path: Path, monkeypatch) -> None:
    outbox = tmp_path / "result-outbox.sqlite3"
    transport = DurableKafkaResultTransport(
        brokers=["unused:9092"],
        topic="agentmesh.runtime.events",
        client_id="p21-test",
        outbox_path=str(outbox),
        publish_timeout_seconds=1,
        retry_min_seconds=0.01,
        retry_max_seconds=0.02,
    )
    producer = _FakeProducer()

    async def fake_ensure():
        return producer

    monkeypatch.setattr(transport, "_ensure_producer", fake_ensure)
    await transport.start()

    delivery = ResultDelivery(
        job_id=7,
        execution_id="exec-7",
        lease_token="lease-7",
        fence_epoch=3,
        dispatcher_epoch=2,
        worker_id="worker-a",
        callback_url="http://control-plane/internal/v1/runtime/jobs/7/callback",
        status="completed",
        payload={
            "workerId": "worker-a",
            "executionId": "exec-7",
            "leaseToken": "lease-7",
            "fenceEpoch": 3,
            "dispatcherEpoch": 2,
            "status": "completed",
            "response": {"answer": "ok"},
        },
        user_id=11,
        conversation_id=13,
    )

    await transport.publish(delivery)

    assert len(producer.messages) == 1
    topic, value, key = producer.messages[0]
    event = json.loads(value)
    assert topic == "agentmesh.runtime.events"
    assert key == b"exec-7"
    assert event["eventType"] == "runtime.execution.result"
    assert event["eventVersion"] == 1
    assert event["executionId"] == "exec-7"
    assert event["payload"]["jobId"] == 7
    assert event["payload"]["callback"]["fenceEpoch"] == 3

    with sqlite3.connect(outbox) as conn:
        count = conn.execute("SELECT COUNT(*) FROM kafka_result_outbox").fetchone()[0]
    assert count == 0, "outbox rows are deleted only after broker acknowledgement"
    await transport.stop()


@pytest.mark.asyncio
async def test_kafka_result_event_id_is_stable_for_duplicate_outcome(tmp_path: Path) -> None:
    outbox = tmp_path / "result-outbox.sqlite3"
    transport = DurableKafkaResultTransport(
        brokers=["unused:9092"],
        topic="agentmesh.runtime.events",
        client_id="p21-test",
        outbox_path=str(outbox),
    )
    transport._initialize_outbox()
    delivery = ResultDelivery(
        job_id=1,
        execution_id="same-execution",
        lease_token="lease",
        fence_epoch=4,
        dispatcher_epoch=1,
        worker_id="worker",
        callback_url="http://unused",
        status="completed",
        payload={"executionId": "same-execution", "status": "completed"},
    )

    event_a = transport._build_event(delivery)
    event_b = transport._build_event(delivery)
    assert event_a["eventId"] == event_b["eventId"]

    encoded = json.dumps(event_a, ensure_ascii=False, separators=(",", ":"))
    transport._insert_outbox(
        event_id=str(event_a["eventId"]),
        partition_key=delivery.execution_id,
        payload_json=encoded,
    )
    transport._insert_outbox(
        event_id=str(event_b["eventId"]),
        partition_key=delivery.execution_id,
        payload_json=encoded,
    )
    with sqlite3.connect(outbox) as conn:
        count = conn.execute("SELECT COUNT(*) FROM kafka_result_outbox").fetchone()[0]
    assert count == 1

class _FlakyProducer:
    def __init__(self) -> None:
        self.attempts = 0

    async def send_and_wait(self, topic: str, value: bytes, *, key: bytes | None = None):
        self.attempts += 1
        if self.attempts == 1:
            raise ConnectionError("synthetic broker outage")
        return object()

    async def stop(self) -> None:
        return


@pytest.mark.asyncio
async def test_kafka_result_transport_health_counts_publish_success_and_retry(tmp_path: Path, monkeypatch) -> None:
    outbox = tmp_path / "result-outbox.sqlite3"
    transport = DurableKafkaResultTransport(
        brokers=["unused:9092"],
        topic="agentmesh.runtime.events",
        client_id="p21-test",
        outbox_path=str(outbox),
        publish_timeout_seconds=1,
        retry_min_seconds=0.01,
        retry_max_seconds=0.02,
    )
    producer = _FlakyProducer()

    async def fake_ensure():
        return producer

    async def fake_close():
        return None

    monkeypatch.setattr(transport, "_ensure_producer", fake_ensure)
    monkeypatch.setattr(transport, "_close_producer", fake_close)
    await transport.start()

    delivery = ResultDelivery(
        job_id=8,
        execution_id="exec-health",
        lease_token="lease-health",
        fence_epoch=5,
        dispatcher_epoch=3,
        worker_id="worker-health",
        callback_url="http://unused",
        status="completed",
        payload={"executionId": "exec-health", "status": "completed"},
    )
    await transport.publish(delivery)
    status = transport.status()
    assert status["outboxEnqueued"] == 1
    assert status["produced"] == 1
    assert status["produceFailed"] == 1
    assert status["pendingOutbox"] == 0
    await transport.stop()
