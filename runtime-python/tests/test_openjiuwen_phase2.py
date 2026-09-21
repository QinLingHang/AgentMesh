"""Phase 2 contracts that do not require a live model endpoint."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from app.agents.openjiuwen import OpenJiuwenToolBridge
from app.agents.openjiuwen_sdk import (
    OpenJiuwenModelAdapter,
    OpenJiuwenSdkDeadlineError,
)
from app.models.contracts import (
    ModelInputAttachment,
    ModelMessage,
    ModelResponse,
)
from app.tools import ToolDefinition, ToolRegistry


class _Gateway:
    def __init__(self) -> None:
        self.requests = []

    async def generate(self, request, on_event=None):
        self.requests.append(request)
        if on_event is not None:
            on_event({"kind": "model_call_completed", "provider": "fake"})
        return ModelResponse(
            content="gateway-result",
            provider="fake",
            model=request.model,
        )


class _BlockingStreamGateway:
    def __init__(self) -> None:
        self.release = asyncio.Event()

    def stream(self, request, on_event=None):
        async def source():
            await self.release.wait()
            yield {"type": "delta", "delta": "late"}

        return source()


@pytest.mark.asyncio
async def test_sdk_model_adapter_keeps_gateway_and_attachment_boundary():
    gateway = _Gateway()
    adapter = OpenJiuwenModelAdapter(
        SimpleNamespace(
            gateway=gateway,
            model="phase2-model",
            vision_model="phase2-vision-model",
        ),
        attachments=[
            ModelInputAttachment(
                name="note.txt",
                media_type="text/plain",
                content_base64="bm90ZQ==",
            )
        ],
        session_id="am-test-session",
    )
    events = []

    result = await adapter.generate(
        [ModelMessage(role="user", content="hello")],
        [],
        events.append,
    )

    assert result.content == "gateway-result"
    assert len(gateway.requests) == 1
    assert gateway.requests[0].model == "phase2-vision-model"
    assert gateway.requests[0].attachments[0].name == "note.txt"
    assert events[0]["executorType"] == "openjiuwen"
    assert events[0]["sessionId"] == "am-test-session"


@pytest.mark.asyncio
async def test_openjiuwen_tool_bridge_uses_registry_for_execution_and_approval():
    registry = ToolRegistry()
    calls = []
    registry.register(
        ToolDefinition(
            name="phase2_tool",
            input_schema={"type": "object"},
        ),
        lambda arguments: calls.append(arguments) or {"ok": True},
    )
    bridge = OpenJiuwenToolBridge(registry)

    result = await bridge.call("phase2_tool", {"value": 1})

    assert result == {"ok": True}
    assert calls == [{"value": 1}]

    approval_registry = ToolRegistry()
    approval_registry.register(
        ToolDefinition(name="phase2_write", risk_level="high"),
        lambda arguments: {"should": "not-run"},
    )
    approval_bridge = OpenJiuwenToolBridge(approval_registry)
    from app.tools import ToolApprovalRequired

    with pytest.raises(ToolApprovalRequired):
        await approval_bridge.call("phase2_write", {})


@pytest.mark.asyncio
async def test_model_adapter_deadline_and_cancellation_are_hard_controls():
    adapter = OpenJiuwenModelAdapter(
        SimpleNamespace(gateway=_Gateway(), model="phase2-model"),
        deadline_at=time.monotonic() - 0.001,
    )
    with pytest.raises(OpenJiuwenSdkDeadlineError):
        await adapter.generate([ModelMessage(role="user", content="late")], [])

    cancel_event = asyncio.Event()
    cancel_event.set()
    cancelled = OpenJiuwenModelAdapter(
        SimpleNamespace(gateway=_Gateway(), model="phase2-model"),
        cancel_event=cancel_event,
    )
    with pytest.raises(asyncio.CancelledError):
        await cancelled.generate([ModelMessage(role="user", content="stop")], [])


@pytest.mark.asyncio
async def test_model_adapter_stream_cancels_while_waiting_for_next_frame():
    cancel_event = asyncio.Event()
    gateway = _BlockingStreamGateway()
    adapter = OpenJiuwenModelAdapter(
        SimpleNamespace(gateway=gateway, model="phase2-model"),
        cancel_event=cancel_event,
    )

    pending = asyncio.create_task(
        adapter.stream(
            [ModelMessage(role="user", content="stream")],
            [],
        ).__anext__()
    )
    await asyncio.sleep(0)
    cancel_event.set()

    with pytest.raises(asyncio.CancelledError):
        await pending
