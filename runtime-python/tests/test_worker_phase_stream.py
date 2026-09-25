"""Knowledge Runtime Worker -> Go metadata phases; requires the normal Runtime dependencies."""

from __future__ import annotations

from types import MethodType, SimpleNamespace

import httpx
import pytest

from app.distributed.execution_manager import DurableExecutionEnvelope, DurableExecutionManager
from app.schemas import RuntimeRequest


def envelope() -> DurableExecutionEnvelope:
    return DurableExecutionEnvelope(
        jobId=12,
        executionId="execution-test",
        leaseToken="lease-test",
        fenceEpoch=4,
        callbackUrl="http://go.invalid/internal/v1/runtime/jobs/12/result",
        request=RuntimeRequest(user_id=9, request_id="worker-phase-stream", task="test", agents=[]),
    )


@pytest.mark.asyncio
async def test_worker_emits_only_whitelisted_metadata_before_result(monkeypatch):
    submissions = []
    order = []

    class FakeClient:
        def __init__(self, **kwargs):
            assert kwargs["trust_env"] is False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def post(self, url, *, json, headers):
            assert url.endswith("/internal/v1/runtime/jobs/12/phase")
            assert headers["X-Internal-Token"] == "test-token"
            submissions.append(json)
            order.append("phase")
            return SimpleNamespace(status_code=200)

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    async def runner(request):
        return SimpleNamespace(model_dump=lambda **_: {})

    async def event_runner(request, sink):
        sink(SimpleNamespace(kind="tool", status="running", title="SECRET_TITLE", detail="SECRET_RESULT"))
        sink(SimpleNamespace(kind="mcp", status="completed", title="SECRET_TITLE", detail="SECRET_ARGUMENT"))
        sink(SimpleNamespace(kind="arbitrary_secret_kind", status="running", detail="SECRET"))
        return await runner(request)

    manager = DurableExecutionManager(
        worker_id="phase-worker", worker_endpoint="http://worker.invalid",
        capacity=1, internal_token="test-token", control_plane_base_url="http://go.invalid",
        heartbeat_interval_seconds=60, callback_timeout_seconds=1,
        callback_max_retries=1, shutdown_grace_seconds=1,
        dedupe_retention_seconds=60, runner=runner, event_runner=event_runner,
    )

    async def fake_callback(self, env, *, status, response=None, error_category=""):
        order.append(status)

    async def no_heartbeat(self):
        return None

    manager._deliver_callback = MethodType(fake_callback, manager)
    manager._send_heartbeat_once = MethodType(no_heartbeat, manager)

    await manager.submit(envelope())
    await next(iter(manager._records.values())).task
    assert order == ["phase", "phase", "completed"]
    assert len(submissions) == 2
    assert [entry["ordinal"] for entry in submissions] == [1, 2]
    assert [entry["phase"] for entry in submissions] == ["tool", "mcp"]
    assert submissions[0]["fenceEpoch"] == 4
    assert all(set(item) == {
        "workerId", "executionId", "leaseToken", "fenceEpoch", "ordinal", "phase", "status",
    } for item in submissions)
    assert "SECRET" not in str(submissions)


@pytest.mark.asyncio
async def test_phase_transport_failure_does_not_fail_business_result(monkeypatch):
    class BrokenClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def post(self, *_args, **_kwargs):
            raise httpx.ConnectError("no phase endpoint")

    monkeypatch.setattr(httpx, "AsyncClient", BrokenClient)
    result_status = []

    async def runner(request):
        return SimpleNamespace(model_dump=lambda **_: {})

    async def event_runner(request, sink):
        sink(SimpleNamespace(kind="model", status="completed"))
        return await runner(request)

    manager = DurableExecutionManager(
        worker_id="phase-worker", worker_endpoint="http://worker.invalid",
        capacity=1, internal_token="token", control_plane_base_url="http://go.invalid",
        heartbeat_interval_seconds=60, callback_timeout_seconds=1,
        callback_max_retries=1, shutdown_grace_seconds=1,
        dedupe_retention_seconds=60, runner=runner, event_runner=event_runner,
    )

    async def fake_callback(self, env, *, status, response=None, error_category=""):
        result_status.append(status)

    async def no_heartbeat(self):
        return None

    manager._deliver_callback = MethodType(fake_callback, manager)
    manager._send_heartbeat_once = MethodType(no_heartbeat, manager)
    await manager.submit(envelope())
    await next(iter(manager._records.values())).task
    assert result_status == ["completed"]