from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Awaitable, Callable

import httpx
from pydantic import BaseModel, ConfigDict, Field

from app.schemas import RuntimeRequest, RuntimeResponse


class DurableExecutionEnvelope(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    job_id: int = Field(alias="jobId")
    execution_id: str = Field(alias="executionId", min_length=1)
    lease_token: str = Field(alias="leaseToken", min_length=1)
    callback_url: str = Field(alias="callbackUrl", min_length=1)
    request: RuntimeRequest


class DurableExecutionAccepted(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    accepted: bool = True
    duplicate: bool = False
    worker_id: str = Field(alias="workerId")


class WorkerUnavailable(RuntimeError):
    def __init__(self, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class _ExecutionRecord:
    envelope: DurableExecutionEnvelope
    task: asyncio.Task[None]
    created_at: float


class DurableExecutionManager:
    """P8 Runtime worker boundary.

    Acceptance and execution are deliberately separated. `submit` performs only
    capacity/draining/idempotency checks and then returns immediately. The actual
    Runtime result is delivered to Go through an idempotent callback.

    The execution ID is stable across safe dispatch retries. Duplicate submits to
    the same worker reuse the existing asyncio Task instead of invoking the Agent
    a second time.
    """

    def __init__(
        self,
        *,
        worker_id: str,
        worker_endpoint: str,
        capacity: int,
        internal_token: str,
        control_plane_base_url: str,
        heartbeat_interval_seconds: float,
        callback_timeout_seconds: float,
        callback_max_retries: int,
        shutdown_grace_seconds: float,
        dedupe_retention_seconds: float,
        runner: Callable[[RuntimeRequest], Awaitable[RuntimeResponse]],
    ) -> None:
        self.worker_id = worker_id.strip()
        self.worker_endpoint = worker_endpoint.rstrip("/")
        self.capacity = max(1, int(capacity))
        self.internal_token = internal_token
        self.control_plane_base_url = control_plane_base_url.rstrip("/")
        self.heartbeat_interval_seconds = max(1.0, heartbeat_interval_seconds)
        self.callback_timeout_seconds = max(1.0, callback_timeout_seconds)
        self.callback_max_retries = max(1, callback_max_retries)
        self.shutdown_grace_seconds = max(1.0, shutdown_grace_seconds)
        self.dedupe_retention_seconds = max(30.0, dedupe_retention_seconds)
        self._runner = runner

        self._lock = asyncio.Lock()
        self._records: dict[str, _ExecutionRecord] = {}
        self._draining = False
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._stopping = False

    @property
    def draining(self) -> bool:
        return self._draining

    def active_count(self) -> int:
        return sum(1 for record in self._records.values() if not record.task.done())

    async def start(self) -> None:
        if self._heartbeat_task is not None:
            return
        self._stopping = False
        self._heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(),
            name="agentmesh-runtime-heartbeat",
        )

    async def stop(self) -> None:
        if self._stopping:
            return
        self._stopping = True
        self._draining = True
        await self._send_heartbeat_once()

        heartbeat = self._heartbeat_task
        self._heartbeat_task = None
        if heartbeat is not None:
            heartbeat.cancel()
            try:
                await heartbeat
            except asyncio.CancelledError:
                pass

        running = [record.task for record in self._records.values() if not record.task.done()]
        if running:
            done, pending = await asyncio.wait(running, timeout=self.shutdown_grace_seconds)
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
        await self._send_heartbeat_once()

    async def submit(self, envelope: DurableExecutionEnvelope) -> DurableExecutionAccepted:
        async with self._lock:
            self._prune_completed_locked()
            existing = self._records.get(envelope.execution_id)
            if existing is not None:
                return DurableExecutionAccepted(
                    accepted=True,
                    duplicate=True,
                    workerId=self.worker_id,
                )
            if self._draining:
                raise WorkerUnavailable("runtime worker is draining", status_code=503)
            if self.active_count() >= self.capacity:
                raise WorkerUnavailable("runtime worker is at capacity", status_code=429)

            task = asyncio.create_task(
                self._execute(envelope),
                name=f"agentmesh-execution-{envelope.execution_id}",
            )
            self._records[envelope.execution_id] = _ExecutionRecord(
                envelope=envelope,
                task=task,
                created_at=time.monotonic(),
            )

        # Heartbeat is best-effort; acceptance must not depend on control-plane
        # heartbeat availability because the caller already holds the lease.
        asyncio.create_task(self._send_heartbeat_once())
        return DurableExecutionAccepted(
            accepted=True,
            duplicate=False,
            workerId=self.worker_id,
        )

    async def cancel(self, execution_id: str) -> bool:
        async with self._lock:
            record = self._records.get(execution_id)
            if record is None:
                return False
            if record.task.done():
                return True
            record.task.cancel()
            return True

    async def _execute(self, envelope: DurableExecutionEnvelope) -> None:
        try:
            response = await self._runner(envelope.request)
            await self._deliver_callback(
                envelope,
                status="completed",
                response=response,
            )
        except asyncio.CancelledError:
            await self._deliver_callback(envelope, status="canceled")
            raise
        except Exception as exc:
            # Never send raw exception text: it may contain prompt/tool/provider
            # data. The class name is enough for control-plane failure taxonomy.
            category = type(exc).__name__.strip() or "RuntimeExecutionError"
            await self._deliver_callback(
                envelope,
                status="failed",
                error_category=category,
            )
        finally:
            asyncio.create_task(self._send_heartbeat_once())

    async def _deliver_callback(
        self,
        envelope: DurableExecutionEnvelope,
        *,
        status: str,
        response: RuntimeResponse | None = None,
        error_category: str = "",
    ) -> None:
        payload: dict[str, object] = {
            "workerId": self.worker_id,
            "executionId": envelope.execution_id,
            "leaseToken": envelope.lease_token,
            "status": status,
        }
        if response is not None:
            payload["response"] = response.model_dump(mode="json", by_alias=True)
        if error_category:
            payload["errorCategory"] = error_category

        headers = {
            "X-Internal-Token": self.internal_token,
            "Content-Type": "application/json",
        }
        timeout = httpx.Timeout(self.callback_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            for attempt in range(self.callback_max_retries):
                try:
                    result = await client.post(envelope.callback_url, json=payload, headers=headers)
                    if 200 <= result.status_code < 300:
                        return
                except Exception:
                    pass
                if attempt + 1 < self.callback_max_retries:
                    await asyncio.sleep(min(0.25 * (2**attempt), 2.0))

    async def _heartbeat_loop(self) -> None:
        while True:
            await self._send_heartbeat_once()
            await asyncio.sleep(self.heartbeat_interval_seconds)

    async def _send_heartbeat_once(self) -> None:
        if not self.control_plane_base_url:
            return
        payload = {
            "workerId": self.worker_id,
            "endpoint": self.worker_endpoint,
            "capacity": self.capacity,
            "activeExecutions": self.active_count(),
            "draining": self._draining,
        }
        headers = {
            "X-Internal-Token": self.internal_token,
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=3.0, trust_env=False) as client:
                await client.post(
                    self.control_plane_base_url + "/internal/v1/runtime/workers/heartbeat",
                    json=payload,
                    headers=headers,
                )
        except Exception:
            # Heartbeats are availability telemetry; they never fail an Agent run.
            return

    def _prune_completed_locked(self) -> None:
        cutoff = time.monotonic() - self.dedupe_retention_seconds
        stale = [
            execution_id
            for execution_id, record in self._records.items()
            if record.task.done() and record.created_at < cutoff
        ]
        for execution_id in stale:
            self._records.pop(execution_id, None)
