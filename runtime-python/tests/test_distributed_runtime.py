from __future__ import annotations

import asyncio
from types import MethodType

import pytest

from app.distributed.execution_manager import (
    DurableExecutionEnvelope,
    DurableExecutionManager,
    WorkerUnavailable,
)
from app.schemas import RuntimeRequest


def request(request_id: str = "durable-request") -> RuntimeRequest:
    return RuntimeRequest(
        user_id=1,
        request_id=request_id,
        task="validate durable execution",
        scheduler="greedy",
        agents=[],
    )


def envelope(execution_id: str = "exec-durable") -> DurableExecutionEnvelope:
    return DurableExecutionEnvelope(
        jobId=7,
        executionId=execution_id,
        leaseToken="lease-durable",
        callbackUrl="http://control-plane.invalid/internal/v1/runtime/jobs/7/result",
        request=request(),
    )


def manager(*, runner, capacity: int = 1, shutdown_grace: float = 0.05) -> DurableExecutionManager:
    return DurableExecutionManager(
        worker_id="worker-durable",
        worker_endpoint="http://runtime.invalid:9572",
        capacity=capacity,
        internal_token="internal-test-token",
        control_plane_base_url="",
        heartbeat_interval_seconds=60,
        callback_timeout_seconds=1,
        callback_max_retries=1,
        shutdown_grace_seconds=shutdown_grace,
        dedupe_retention_seconds=60,
        runner=runner,
    )


async def capture_callbacks(target: list[dict], self, env, *, status, response=None, error_category=""):
    target.append(
        {
            "execution_id": env.execution_id,
            "status": status,
            "response": response,
            "error_category": error_category,
        }
    )


@pytest.mark.asyncio
async def test_execution_id_is_idempotent_and_duplicate_never_runs_twice():
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0
    callbacks: list[dict] = []

    async def runner(_):
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return object()

    m = manager(runner=runner)
    m._deliver_callback = MethodType(lambda self, env, **kw: capture_callbacks(callbacks, self, env, **kw), m)

    first = await m.submit(envelope())
    await started.wait()
    duplicate = await m.submit(envelope())

    assert first.accepted is True and first.duplicate is False
    assert duplicate.accepted is True and duplicate.duplicate is True
    assert calls == 1

    release.set()
    await asyncio.gather(*(record.task for record in m._records.values()))
    assert calls == 1
    assert callbacks[0]["status"] == "completed"


@pytest.mark.asyncio
async def test_capacity_rejection_happens_before_acceptance():
    release = asyncio.Event()

    async def runner(_):
        await release.wait()
        return object()

    m = manager(runner=runner, capacity=1)
    m._deliver_callback = MethodType(lambda self, env, **kw: capture_callbacks([], self, env, **kw), m)

    await m.submit(envelope("exec-one"))
    with pytest.raises(WorkerUnavailable) as exc:
        await m.submit(envelope("exec-two"))
    assert exc.value.status_code == 429
    assert m.active_count() == 1

    release.set()
    await asyncio.gather(*(record.task for record in m._records.values()))


@pytest.mark.asyncio
async def test_draining_worker_rejects_before_acceptance():
    async def runner(_):
        return object()

    m = manager(runner=runner)
    m._draining = True
    with pytest.raises(WorkerUnavailable) as exc:
        await m.submit(envelope())
    assert exc.value.status_code == 503
    assert m.active_count() == 0


@pytest.mark.asyncio
async def test_cancel_stops_execution_and_emits_canceled_callback():
    started = asyncio.Event()
    callbacks: list[dict] = []

    async def runner(_):
        started.set()
        await asyncio.Event().wait()

    m = manager(runner=runner)
    m._deliver_callback = MethodType(lambda self, env, **kw: capture_callbacks(callbacks, self, env, **kw), m)

    await m.submit(envelope())
    await started.wait()
    assert await m.cancel("exec-durable") is True
    await asyncio.gather(*(record.task for record in m._records.values()), return_exceptions=True)

    assert callbacks == [
        {
            "execution_id": "exec-durable",
            "status": "canceled",
            "response": None,
            "error_category": "",
        }
    ]


@pytest.mark.asyncio
async def test_failure_callback_uses_exception_class_only_never_raw_secret_detail():
    callbacks: list[dict] = []

    class ProviderFailure(RuntimeError):
        pass

    async def runner(_):
        raise ProviderFailure("secret-token=DO-NOT-LEAK")

    m = manager(runner=runner)
    m._deliver_callback = MethodType(lambda self, env, **kw: capture_callbacks(callbacks, self, env, **kw), m)

    await m.submit(envelope())
    await asyncio.gather(*(record.task for record in m._records.values()))

    assert callbacks[0]["status"] == "failed"
    assert callbacks[0]["error_category"] == "ProviderFailure"
    serialized = repr(callbacks)
    assert "DO-NOT-LEAK" not in serialized
    assert "secret-token" not in serialized


@pytest.mark.asyncio
async def test_graceful_stop_enters_draining_and_cancels_execution_after_grace():
    started = asyncio.Event()
    callbacks: list[dict] = []

    async def runner(_):
        started.set()
        await asyncio.Event().wait()

    m = manager(runner=runner, shutdown_grace=0.01)
    m._deliver_callback = MethodType(lambda self, env, **kw: capture_callbacks(callbacks, self, env, **kw), m)

    await m.submit(envelope())
    await started.wait()
    await m.stop()

    assert m.draining is True
    assert m.active_count() == 0
    assert any(item["status"] == "canceled" for item in callbacks)


@pytest.mark.asyncio
async def test_completed_execution_remains_in_dedupe_window():
    calls = 0
    callbacks: list[dict] = []

    async def runner(_):
        nonlocal calls
        calls += 1
        return object()

    m = manager(runner=runner)
    m._deliver_callback = MethodType(lambda self, env, **kw: capture_callbacks(callbacks, self, env, **kw), m)

    await m.submit(envelope())
    await asyncio.gather(*(record.task for record in m._records.values()))
    duplicate = await m.submit(envelope())

    assert duplicate.duplicate is True
    assert calls == 1
