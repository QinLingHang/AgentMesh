from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Awaitable, Callable

import httpx
from pydantic import BaseModel, ConfigDict, Field

from app.schemas import RuntimeRequest, RuntimeResponse
from app.distributed.result_transport import HttpResultTransport, ResultDelivery, ResultTransport


logger = logging.getLogger(__name__)


class DurableExecutionEnvelope(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    job_id: int = Field(alias="jobId")
    execution_id: str = Field(alias="executionId", min_length=1)
    lease_token: str = Field(alias="leaseToken", min_length=1)
    fence_epoch: int = Field(default=0, alias="fenceEpoch")
    dispatcher_epoch: int = Field(default=0, alias="dispatcherEpoch")
    callback_url: str = Field(alias="callbackUrl", min_length=1)
    request: RuntimeRequest


class DurableExecutionAccepted(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    accepted: bool = True
    duplicate: bool = False
    worker_id: str = Field(alias="workerId")
    fence_epoch: int = Field(default=0, alias="fenceEpoch")


class WorkerUnavailable(RuntimeError):
    def __init__(self, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class _ExecutionRecord:
    envelope: DurableExecutionEnvelope
    task: asyncio.Task[None]
    created_at: float
    result_pending: bool = False
    finalized: asyncio.Event = field(default_factory=asyncio.Event)


class DurableExecutionManager:
    """Durable Runtime Runtime worker boundary.

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
        event_runner: Callable[[RuntimeRequest, Callable[[object], None]], Awaitable[RuntimeResponse]] | None = None,
        node_id: str = "",
        node_zone: str = "",
        node_version: str = "",
        node_capacity: int = 0,
        result_transport: ResultTransport | None = None,
    ) -> None:
        self.worker_id = worker_id.strip()
        self.worker_endpoint = worker_endpoint.rstrip("/")
        self.capacity = max(1, int(capacity))
        self.node_id = (node_id or self.worker_id).strip()
        self.node_zone = node_zone.strip()
        self.node_version = node_version.strip()
        self.node_capacity = max(self.capacity, int(node_capacity or self.capacity))
        self.started_at = datetime.now(timezone.utc)
        self.internal_token = internal_token
        self.control_plane_base_url = control_plane_base_url.rstrip("/")
        self.heartbeat_interval_seconds = max(1.0, heartbeat_interval_seconds)
        self.callback_timeout_seconds = max(1.0, callback_timeout_seconds)
        self.callback_max_retries = max(1, callback_max_retries)
        self.shutdown_grace_seconds = max(1.0, shutdown_grace_seconds)
        self.dedupe_retention_seconds = max(30.0, dedupe_retention_seconds)
        self._runner = runner
        self._event_runner = event_runner
        self._result_transport = result_transport or HttpResultTransport(
            internal_token=internal_token,
            timeout_seconds=callback_timeout_seconds,
            max_retries=callback_max_retries,
        )

        self._lock = asyncio.Lock()
        self._records: dict[str, _ExecutionRecord] = {}
        self._draining = False
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._stopping = False
        self._heartbeat_sent_total = 0
        self._heartbeat_failed_total = 0
        self._heartbeat_last_success_at: str | None = None
        self._heartbeat_last_failure_at: str | None = None
        self._heartbeat_last_error_category: str | None = None

    @property
    def draining(self) -> bool:
        return self._draining

    def active_count(self) -> int:
        return sum(1 for record in self._records.values() if not record.task.done())

    def heartbeat_status(self) -> dict[str, object]:
        return {
            "sent": self._heartbeat_sent_total,
            "failed": self._heartbeat_failed_total,
            "lastSuccessAt": self._heartbeat_last_success_at,
            "lastFailureAt": self._heartbeat_last_failure_at,
            "lastErrorCategory": self._heartbeat_last_error_category,
        }

    def result_transport_status(self) -> dict[str, object]:
        status_fn = getattr(self._result_transport, "status", None)
        if callable(status_fn):
            value = status_fn()
            if isinstance(value, dict):
                return value
        return {"mode": "unknown"}

    def active_execution_leases(self) -> list[dict[str, object]]:
        leases: list[dict[str, object]] = []
        for record in self._records.values():
            if record.task.done():
                continue
            envelope = record.envelope
            lease: dict[str, object] = {
                "jobId": envelope.job_id,
                "executionId": envelope.execution_id,
                "leaseToken": envelope.lease_token,
                "fenceEpoch": envelope.fence_epoch,
            }
            if record.result_pending:
                lease["resultPending"] = True
            leases.append(lease)
        return leases

    async def set_draining(self, draining: bool) -> None:
        self._draining = bool(draining)
        await self._send_heartbeat_once()

    async def start(self) -> None:
        if self._heartbeat_task is not None:
            return
        self._stopping = False
        await self._result_transport.start()
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
        await self._result_transport.stop()

    async def submit(self, envelope: DurableExecutionEnvelope) -> DurableExecutionAccepted:
        async with self._lock:
            self._prune_completed_locked()
            existing = self._records.get(envelope.execution_id)
            if existing is not None:
                old = existing.envelope
                if envelope.fence_epoch < old.fence_epoch:
                    raise WorkerUnavailable("stale execution fence", status_code=409)
                if envelope.fence_epoch == old.fence_epoch:
                    if envelope.lease_token != old.lease_token or envelope.job_id != old.job_id:
                        raise WorkerUnavailable("conflicting execution ownership", status_code=409)
                    return DurableExecutionAccepted(
                        accepted=True,
                        duplicate=True,
                        workerId=self.worker_id,
                        fenceEpoch=old.fence_epoch,
                    )
            if self._draining:
                raise WorkerUnavailable("runtime worker is draining", status_code=503)
            # A newer fence supersedes the old attempt; it does not consume a
            # second permanent capacity slot. Its old outbox event remains
            # durable and is rejected by the Go fencing check if delivered.
            occupied = self.active_count() - int(existing is not None and not existing.task.done())
            if occupied >= self.capacity:
                raise WorkerUnavailable("runtime worker is at capacity", status_code=429)
            if existing is not None and not existing.task.done():
                existing.task.cancel()

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
            fenceEpoch=envelope.fence_epoch,
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
        # Trace delivery is a bounded, best-effort side channel. No user text,
        # tool arguments/results or raw trace titles ever leave this worker.
        phase_queue: asyncio.Queue[tuple[int, str, str]] | None = None
        phase_sender: asyncio.Task[None] | None = None
        sequence = 0
        if self._event_runner is not None and self.control_plane_base_url and envelope.fence_epoch > 0:
            phase_queue = asyncio.Queue(maxsize=64)
            phase_sender = asyncio.create_task(
                self._send_worker_phases(envelope, phase_queue),
                name=f"agentmesh-phase-{envelope.execution_id}",
            )

        loop = asyncio.get_running_loop()

        def on_trace(trace: object) -> None:
            nonlocal sequence
            if phase_queue is None or not self._is_current_attempt(envelope):
                return
            kind = str(getattr(trace, "kind", "")).strip().lower()
            status = str(getattr(trace, "status", "")).strip().lower()
            if kind not in {"task", "planner", "scheduler", "agent", "tool", "mcp", "rag", "knowledge", "memory", "model"}:
                return
            if status not in {"running", "completed", "error", "skipped"} or sequence >= 256:
                return
            sequence += 1
            ordinal = sequence

            def enqueue() -> None:
                try:
                    phase_queue.put_nowait((ordinal, kind, status))
                except asyncio.QueueFull:
                    # Never block model/tool execution on disconnected observability.
                    pass

            loop.call_soon_threadsafe(enqueue)

        async def flush_phases() -> None:
            if phase_sender is None or phase_queue is None:
                return
            # Run scheduled callbacks before waiting for pending HTTP writes.
            await asyncio.sleep(0)
            try:
                await asyncio.wait_for(phase_queue.join(), timeout=1.5)
            except asyncio.TimeoutError:
                pass

        try:
            if self._event_runner is not None and phase_queue is not None:
                response = await self._event_runner(envelope.request, on_trace)
            else:
                response = await self._runner(envelope.request)
        except asyncio.CancelledError:
            # Do not generate a second, conflicting outcome for an attempt
            # canceled by a higher fence. A previously stored outbox event is
            # preserved and Go will apply the authoritative fence.
            if self._is_current_attempt(envelope):
                await flush_phases()
                await self._deliver_callback(envelope, status="canceled")
            raise
        except Exception as exc:
            # Never send raw exception text: it may contain prompt/tool/provider
            # data. The class name is enough for control-plane failure taxonomy.
            category = type(exc).__name__.strip() or "RuntimeExecutionError"
            await flush_phases()
            await self._deliver_callback(
                envelope,
                status="failed",
                error_category=category,
            )
        else:
            await flush_phases()
            await self._deliver_callback(
                envelope,
                status="completed",
                response=response,
            )
        finally:
            if phase_sender is not None:
                phase_sender.cancel()
                await asyncio.gather(phase_sender, return_exceptions=True)
            asyncio.create_task(self._send_heartbeat_once())

    async def _send_worker_phases(
        self,
        envelope: DurableExecutionEnvelope,
        queue: asyncio.Queue[tuple[int, str, str]],
    ) -> None:
        endpoint = (
            f"{self.control_plane_base_url}/internal/v1/runtime/jobs/"
            f"{envelope.job_id}/phase"
        )
        headers = {"X-Internal-Token": self.internal_token}
        async with httpx.AsyncClient(timeout=1.5, trust_env=False) as client:
            while True:
                ordinal, kind, status = await queue.get()
                try:
                    if not self._is_current_attempt(envelope):
                        continue
                    payload = {
                        "workerId": self.worker_id,
                        "executionId": envelope.execution_id,
                        "leaseToken": envelope.lease_token,
                        "fenceEpoch": envelope.fence_epoch,
                        "ordinal": ordinal,
                        "phase": kind,
                        "status": status,
                    }
                    try:
                        await client.post(endpoint, json=payload, headers=headers)
                    except (httpx.HTTPError, OSError):
                        # Loss of transient phase telemetry never retries a job.
                        pass
                finally:
                    queue.task_done()

    def _is_current_attempt(self, envelope: DurableExecutionEnvelope) -> bool:
        record = self._records.get(envelope.execution_id)
        return record is not None and record.envelope is envelope

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
            "fenceEpoch": envelope.fence_epoch,
            "dispatcherEpoch": envelope.dispatcher_epoch,
            "status": status,
        }
        if response is not None:
            payload["response"] = response.model_dump(mode="json", by_alias=True)
        if error_category:
            payload["errorCategory"] = error_category

        kafka_delivery = self.result_transport_status().get("mode") == "kafka"
        record = self._records.get(envelope.execution_id)
        current = record is not None and record.envelope is envelope
        if kafka_delivery and current:
            # publish() persists synchronously before its first await. The
            # resultPending flag cannot reach a heartbeat until that INSERT
            # has committed; the on_persisted hook forces an early heartbeat.
            record.result_pending = True
        await self._result_transport.publish(
            ResultDelivery(
                job_id=envelope.job_id,
                execution_id=envelope.execution_id,
                lease_token=envelope.lease_token,
                fence_epoch=envelope.fence_epoch,
                dispatcher_epoch=envelope.dispatcher_epoch,
                worker_id=self.worker_id,
                callback_url=envelope.callback_url,
                status=status,
                payload=payload,
                user_id=getattr(envelope.request, "user_id", None),
                conversation_id=getattr(envelope.request, "conversation_id", None),
                on_persisted=self._send_heartbeat_once if kafka_delivery and current else None,
            )
        )
        if kafka_delivery and current and self.control_plane_base_url:
            # Kafka broker ACK is NOT a business ACK. Keep the execution and
            # its heartbeat lease alive until Go confirms terminal state.
            await record.finalized.wait()

    async def _heartbeat_loop(self) -> None:
        while True:
            await self._send_heartbeat_once()
            await asyncio.sleep(self.heartbeat_interval_seconds)

    async def _send_heartbeat_once(self) -> None:
        if not self.control_plane_base_url:
            return
        payload = {
            "workerId": self.worker_id,
            "nodeId": self.node_id,
            "zone": self.node_zone,
            "version": self.node_version,
            "startedAt": self.started_at.isoformat().replace("+00:00", "Z"),
            "endpoint": self.worker_endpoint,
            "capacity": self.capacity,
            "nodeCapacity": self.node_capacity,
            "activeExecutions": self.active_count(),
            "draining": self._draining,
            "executionLeases": self.active_execution_leases(),
        }
        headers = {
            "X-Internal-Token": self.internal_token,
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=3.0, trust_env=False) as client:
                response = await client.post(
                    self.control_plane_base_url + "/internal/v1/runtime/workers/heartbeat",
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
                # Old control planes / test doubles may omit the new optional
                # acknowledgement field. Never infer finalization from 200.
                json_method = getattr(response, "json", None)
                body = json_method() if callable(json_method) else None
                data = body.get("data", {}) if isinstance(body, dict) else {}
                terminal = data.get("terminalExecutionIds", []) if isinstance(data, dict) else []
                if isinstance(terminal, list):
                    for execution_id in terminal:
                        record = self._records.get(execution_id)
                        if record is not None and record.result_pending:
                            record.finalized.set()
            self._heartbeat_sent_total += 1
            self._heartbeat_last_success_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            self._heartbeat_last_error_category = None
        except Exception as exc:
            # Heartbeats must not fail an Agent run, but failures are observable so
            # a worker cannot remain silently OFFLINE while executions are active.
            self._heartbeat_failed_total += 1
            self._heartbeat_last_failure_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            self._heartbeat_last_error_category = type(exc).__name__.strip() or "HeartbeatError"
            logger.warning(
                "runtime worker heartbeat failed: category=%s",
                self._heartbeat_last_error_category,
            )
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
