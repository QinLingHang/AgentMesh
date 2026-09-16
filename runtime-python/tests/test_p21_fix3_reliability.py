"""P21 FIX3 regressions for business ACK and attempt-level fencing."""
from __future__ import annotations

import asyncio
import httpx
import pytest

from app.distributed.execution_manager import (
    DurableExecutionEnvelope,
    DurableExecutionManager,
    WorkerUnavailable,
)
from app.schemas import RuntimeRequest, RuntimeResponse


def _envelope(fence: int, token: str = "lease-1") -> DurableExecutionEnvelope:
    return DurableExecutionEnvelope(
        jobId=17,
        executionId="one-execution",
        leaseToken=token,
        fenceEpoch=fence,
        callbackUrl="http://unused/internal/v1/runtime/jobs/17/result",
        request=RuntimeRequest(user_id=1, request_id="p21-fix3", task="hello", agents=[]),
    )


def _manager(runner) -> DurableExecutionManager:
    return DurableExecutionManager(
        worker_id="worker-fix3",
        worker_endpoint="http://runtime.invalid",
        capacity=1,
        internal_token="qa-only-token",
        control_plane_base_url="",
        heartbeat_interval_seconds=60,
        callback_timeout_seconds=1,
        callback_max_retries=1,
        shutdown_grace_seconds=1,
        dedupe_retention_seconds=60,
        runner=runner,
    )


def _response() -> RuntimeResponse:
    return RuntimeResponse(
        request_id="p21-fix3", status="COMPLETED", answer="[Mock Answer]",
        scheduler="greedy",
        task_profile={"required_capabilities": [], "complexity": "low", "risk_level": "low",
                      "modality": ["text"], "parallelizable": False},
        selected_agents=[], estimated_cost=0.0, elapsed_ms=0,
        trace=[], dag={"nodes": [], "edges": []}, agent_feedback=[],
    )


@pytest.mark.asyncio
async def test_higher_fence_replaces_old_attempt_but_lower_and_conflicting_are_rejected():
    old_started = asyncio.Event()
    invoked: list[str] = []
    callbacks: list[str] = []

    async def runner(request):
        invoked.append(request.request_id)
        if len(invoked) == 1:
            old_started.set()
            await asyncio.Event().wait()
        return object()

    manager = _manager(runner)

    async def fake_callback(envelope, *, status, **kwargs):
        callbacks.append(f"{envelope.fence_epoch}:{status}")

    manager._deliver_callback = fake_callback
    first = _envelope(3)
    assert (await manager.submit(first)).duplicate is False
    old_task = manager._records[first.execution_id].task
    await asyncio.wait_for(old_started.wait(), timeout=1)
    assert (await manager.submit(_envelope(3))).duplicate is True
    with pytest.raises(WorkerUnavailable) as conflict:
        await manager.submit(_envelope(3, token="wrong-owner"))
    assert conflict.value.status_code == 409
    with pytest.raises(WorkerUnavailable) as stale:
        await manager.submit(_envelope(2))
    assert stale.value.status_code == 409

    newer = _envelope(4, token="lease-new")
    accepted = await manager.submit(newer)
    assert accepted.accepted and not accepted.duplicate
    assert accepted.fence_epoch == 4
    await asyncio.wait_for(
        asyncio.gather(old_task, manager._records[newer.execution_id].task, return_exceptions=True),
        timeout=2,
    )
    assert len(invoked) == 2
    assert callbacks == ["4:completed"], "superseded attempt must not emit a new cancel callback"


@pytest.mark.asyncio
async def test_broker_ack_keeps_execution_active_until_control_plane_ack():
    broker_ack = asyncio.Event()

    class FakeKafka:
        def status(self):
            return {"mode": "kafka"}

        async def publish(self, delivery):
            if delivery.on_persisted is not None:
                await delivery.on_persisted()
            broker_ack.set()  # Broker acknowledged, Go has NOT processed yet.

    async def runner(_):
        return _response()

    manager = _manager(runner)
    manager.control_plane_base_url = "http://control.invalid"
    manager._result_transport = FakeKafka()

    async def heartbeat():
        return None

    manager._send_heartbeat_once = heartbeat
    envelope = _envelope(5)
    await manager.submit(envelope)
    await asyncio.wait_for(broker_ack.wait(), timeout=1)
    await asyncio.sleep(0)
    record = manager._records[envelope.execution_id]
    assert manager.active_count() == 1
    assert not record.task.done()
    assert not record.finalized.is_set()
    assert manager.active_execution_leases()[0]["resultPending"] is True

    record.finalized.set()  # The Go business ACK, distinct from broker ACK.
    await asyncio.wait_for(record.task, timeout=1)
    assert manager.active_count() == 0


@pytest.mark.asyncio
async def test_heartbeat_releases_result_only_after_explicit_terminal_ack(monkeypatch):
    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"code": 0, "data": {"terminalExecutionIds": ["one-execution"]}}

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            assert kwargs["json"]["executionLeases"][0]["resultPending"] is True
            return Response()

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    manager = _manager(lambda req: asyncio.sleep(100))
    manager.control_plane_base_url = "http://control.invalid"
    await manager.submit(_envelope(7))
    record = manager._records["one-execution"]
    record.result_pending = True
    assert not record.finalized.is_set()
    await manager._send_heartbeat_once()
    assert record.finalized.is_set()
    record.task.cancel()
    await asyncio.gather(record.task, return_exceptions=True)
