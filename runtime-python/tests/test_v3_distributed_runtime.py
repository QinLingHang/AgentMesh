from __future__ import annotations

import asyncio
from types import MethodType

import pytest

from app.distributed.execution_manager import (
    DurableExecutionEnvelope,
    DurableExecutionManager,
    WorkerUnavailable,
)
from app.schemas import RuntimeRequest, RuntimeResponse


def _request(request_id: str = "v3-request") -> RuntimeRequest:
    return RuntimeRequest(
        user_id=7,
        request_id=request_id,
        task="validate v3 multi-node execution",
        scheduler="adaptive",
        agents=[],
    )


def _envelope(execution_id: str = "exec-v3", *, fence: int = 3, dispatcher: int = 9) -> DurableExecutionEnvelope:
    return DurableExecutionEnvelope(
        jobId=31,
        executionId=execution_id,
        leaseToken="lease-v3",
        fenceEpoch=fence,
        dispatcherEpoch=dispatcher,
        callbackUrl="http://control-plane.invalid/internal/v1/runtime/jobs/31/result",
        request=_request(execution_id),
    )


def _response(request_id: str = "v3-request") -> RuntimeResponse:
    return RuntimeResponse(
        request_id=request_id,
        status="COMPLETED",
        answer="ok",
        scheduler="adaptive",
        task_profile={
            "required_capabilities": [],
            "complexity": "low",
            "risk_level": "low",
            "modality": ["text"],
            "parallelizable": False,
        },
        selected_agents=[],
        estimated_cost=0.0,
        elapsed_ms=0,
        trace=[],
        dag={"nodes": [], "edges": []},
        agent_feedback=[],
    )


def _manager(*, runner, capacity: int = 2) -> DurableExecutionManager:
    return DurableExecutionManager(
        worker_id="worker-v3-a",
        worker_endpoint="http://runtime-node-a.invalid:9572",
        capacity=capacity,
        internal_token="internal-test-token",
        control_plane_base_url="http://control-plane.invalid",
        heartbeat_interval_seconds=60,
        callback_timeout_seconds=1,
        callback_max_retries=1,
        shutdown_grace_seconds=.05,
        dedupe_retention_seconds=60,
        runner=runner,
        node_id="node-a",
        node_zone="zone-a",
        node_version="3.0.0-dev",
        node_capacity=8,
    )


@pytest.mark.asyncio
async def test_v3_heartbeat_carries_node_topology_and_active_lease_fence(monkeypatch):
    release = asyncio.Event()
    captured: list[dict] = []

    async def runner(_):
        await release.wait()
        return _response()

    class Response:
        status_code = 200

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, *, json, headers):
            captured.append({"url": url, "json": json, "headers": headers})
            return Response()

    monkeypatch.setattr("app.distributed.execution_manager.httpx.AsyncClient", FakeClient)

    manager = _manager(runner=runner)
    accepted = await manager.submit(_envelope())
    assert accepted.accepted is True
    await manager._send_heartbeat_once()

    heartbeat = next(item for item in captured if item["url"].endswith("/internal/v1/runtime/workers/heartbeat"))
    payload = heartbeat["json"]
    assert payload["workerId"] == "worker-v3-a"
    assert payload["nodeId"] == "node-a"
    assert payload["zone"] == "zone-a"
    assert payload["version"] == "3.0.0-dev"
    assert payload["nodeCapacity"] == 8
    assert payload["activeExecutions"] == 1
    assert payload["executionLeases"] == [
        {
            "jobId": 31,
            "executionId": "exec-v3",
            "leaseToken": "lease-v3",
            "fenceEpoch": 3,
        }
    ]
    assert "internal-test-token" not in repr(payload)

    release.set()
    await asyncio.gather(*(record.task for record in manager._records.values()))


@pytest.mark.asyncio
async def test_v3_callback_propagates_worker_fence_and_dispatcher_epoch():
    captured: list[dict] = []

    async def runner(_):
        return _response()

    manager = _manager(runner=runner)

    async def fake_callback(self, envelope, *, status, response=None, error_category=""):
        captured.append({
            "workerId": self.worker_id,
            "executionId": envelope.execution_id,
            "leaseToken": envelope.lease_token,
            "fenceEpoch": envelope.fence_epoch,
            "dispatcherEpoch": envelope.dispatcher_epoch,
            "status": status,
        })

    manager._deliver_callback = MethodType(fake_callback, manager)
    await manager.submit(_envelope(fence=17, dispatcher=42))
    await asyncio.gather(*(record.task for record in manager._records.values()))

    assert captured == [{
        "workerId": "worker-v3-a",
        "executionId": "exec-v3",
        "leaseToken": "lease-v3",
        "fenceEpoch": 17,
        "dispatcherEpoch": 42,
        "status": "completed",
    }]


@pytest.mark.asyncio
async def test_v3_draining_rejects_new_work_but_preserves_running_execution():
    started = asyncio.Event()
    release = asyncio.Event()

    async def runner(_):
        started.set()
        await release.wait()
        return _response()

    manager = _manager(runner=runner, capacity=2)
    manager.control_plane_base_url = ""
    manager._deliver_callback = MethodType(lambda self, *args, **kwargs: asyncio.sleep(0), manager)

    await manager.submit(_envelope("running"))
    await started.wait()
    await manager.set_draining(True)

    with pytest.raises(WorkerUnavailable) as exc:
        await manager.submit(_envelope("new-work"))
    assert exc.value.status_code == 503
    assert manager.active_count() == 1

    release.set()
    await asyncio.gather(*(record.task for record in manager._records.values()))


@pytest.mark.asyncio
async def test_v3_node_capacity_never_reduces_below_worker_capacity():
    async def runner(_):
        return _response()

    manager = DurableExecutionManager(
        worker_id="worker-v3",
        worker_endpoint="http://runtime.invalid:9572",
        capacity=6,
        internal_token="token",
        control_plane_base_url="",
        heartbeat_interval_seconds=60,
        callback_timeout_seconds=1,
        callback_max_retries=1,
        shutdown_grace_seconds=1,
        dedupe_retention_seconds=60,
        runner=runner,
        node_id="node-v3",
        node_capacity=2,
    )
    assert manager.capacity == 6
    assert manager.node_capacity == 6
