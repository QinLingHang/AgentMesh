"""P21: a failed Kafka producer startup must release the *local* producer.

These are deterministic lifecycle regressions, not substitutes for the separate
real-broker and complete Dispatcher -> Worker fault-injection release gates.
"""
from __future__ import annotations

import asyncio
import importlib.util
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# Import the actual production module in isolation: importing app.distributed
# also imports unrelated MCP/A2A integrations, unnecessary for transport tests.
_MODULE_NAME = "agentmesh_p21_result_transport_isolated"
_SOURCE = Path(__file__).resolve().parents[1] / "app" / "distributed" / "result_transport.py"
_spec = importlib.util.spec_from_file_location(_MODULE_NAME, _SOURCE)
assert _spec is not None and _spec.loader is not None
_module = importlib.util.module_from_spec(_spec)
sys.modules[_MODULE_NAME] = _module
_spec.loader.exec_module(_module)
DurableKafkaResultTransport = _module.DurableKafkaResultTransport
ResultDelivery = _module.ResultDelivery


def _transport(tmp_path: Path) -> DurableKafkaResultTransport:
    return DurableKafkaResultTransport(
        brokers=["isolated-qa:9092"],
        topic="p21.qa.results",
        client_id="p21-producer-cleanup-test",
        outbox_path=str(tmp_path / "qa-outbox.sqlite3"),
        publish_timeout_seconds=1,
        retry_min_seconds=0.01,
        retry_max_seconds=0.02,
    )


def _delivery() -> ResultDelivery:
    return ResultDelivery(
        job_id=7,
        execution_id="qa-exec",
        lease_token="qa-lease",
        fence_epoch=2,
        dispatcher_epoch=1,
        worker_id="qa-worker",
        callback_url="http://qa.invalid/internal/result",
        status="completed",
        payload={"executionId": "qa-exec", "status": "completed"},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [OSError("broker unavailable"), asyncio.CancelledError()])
async def test_failed_producer_start_always_stops_unassigned_instance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: BaseException
) -> None:
    producers = []

    class FailedProducer:
        def __init__(self, **kwargs):
            self.started = 0
            self.stopped = 0
            producers.append(self)

        async def start(self):
            self.started += 1
            raise failure

        async def stop(self):
            self.stopped += 1

    monkeypatch.setitem(sys.modules, "aiokafka", SimpleNamespace(AIOKafkaProducer=FailedProducer))
    transport = _transport(tmp_path)
    with pytest.raises(type(failure)):
        await transport._ensure_producer()

    assert len(producers) == 1
    assert producers[0].started == producers[0].stopped == 1
    assert transport._producer is None
    assert transport.status()["brokerConnected"] is False


@pytest.mark.asyncio
async def test_cleanup_failure_does_not_mask_original_start_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    producers = []

    class FailedProducer:
        def __init__(self, **kwargs):
            self.stopped = 0
            producers.append(self)

        async def start(self):
            raise ConnectionError("original startup failure")

        async def stop(self):
            self.stopped += 1
            raise RuntimeError("cleanup also failed")

    monkeypatch.setitem(sys.modules, "aiokafka", SimpleNamespace(AIOKafkaProducer=FailedProducer))
    transport = _transport(tmp_path)
    with pytest.raises(ConnectionError, match="original startup failure"):
        await transport._ensure_producer()
    assert len(producers) == 1 and producers[0].stopped == 1
    assert transport._producer is None
    assert "cleanup after failed startup raised RuntimeError" in caplog.text
    assert "cleanup also failed" not in caplog.text


@pytest.mark.asyncio
async def test_failed_start_keeps_outbox_and_retry_publishes_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    producers = []
    messages = []
    pending_at_failure = []
    transport = _transport(tmp_path)

    class RecoveringProducer:
        def __init__(self, **kwargs):
            self.stopped = 0
            self.sequence = len(producers)
            producers.append(self)

        async def start(self):
            if self.sequence == 0:
                with sqlite3.connect(transport._outbox_path) as conn:
                    pending_at_failure.append(
                        conn.execute("SELECT COUNT(*) FROM kafka_result_outbox").fetchone()[0]
                    )
                raise ConnectionError("QA broker down")

        async def send_and_wait(self, topic, payload, *, key):
            messages.append((topic, payload, key))
            return object()

        async def stop(self):
            self.stopped += 1

    monkeypatch.setitem(sys.modules, "aiokafka", SimpleNamespace(AIOKafkaProducer=RecoveringProducer))
    await transport.start()
    try:
        await asyncio.wait_for(transport.publish(_delivery()), timeout=3)
        assert pending_at_failure == [1], "failure must not delete the durable outbox entry"
        assert len(producers) == 2
        assert producers[0].stopped == 1
        assert producers[1].stopped == 0, "a successfully started producer remains in use"
        assert len(messages) == 1
        assert messages[0][0] == "p21.qa.results"
        assert transport.status()["produced"] == 1
        assert transport.status()["produceFailed"] == 1
        assert transport.status()["pendingOutbox"] == 0
    finally:
        await transport.stop()
    assert producers[1].stopped == 1


@pytest.mark.asyncio
async def test_cancelling_in_flight_start_closes_local_producer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = asyncio.Event()
    producers = []

    class SlowProducer:
        def __init__(self, **kwargs):
            self.stopped = 0
            producers.append(self)

        async def start(self):
            created.set()
            await asyncio.Event().wait()

        async def stop(self):
            self.stopped += 1

    monkeypatch.setitem(sys.modules, "aiokafka", SimpleNamespace(AIOKafkaProducer=SlowProducer))
    transport = _transport(tmp_path)
    task = asyncio.create_task(transport._ensure_producer())
    await asyncio.wait_for(created.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=1)
    assert len(producers) == 1 and producers[0].stopped == 1
    assert transport._producer is None
