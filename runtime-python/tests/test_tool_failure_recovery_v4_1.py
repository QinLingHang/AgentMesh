from __future__ import annotations

import pytest

from app.models import ModelGateway, ModelResponse, ToolCall
from app.tools import ToolDefinition, ToolError, ToolErrorType, ToolLoopRunner, ToolRegistry


class _RecoveringProvider:
    name = "recovering"

    def __init__(self, tool_name: str):
        self.tool_name = tool_name
        self.calls = 0
        self.requests = []

    async def generate(self, request):
        self.calls += 1
        self.requests.append(request)
        if self.calls == 1:
            return ModelResponse(
                content="",
                provider=self.name,
                model=request.model,
                tool_calls=[
                    ToolCall(
                        id="tool-1",
                        name=self.tool_name,
                        arguments={"path": r"E:\AIProject"},
                    )
                ],
            )

        tool_observation = next(
            message
            for message in request.messages
            if message.role == "tool"
        )
        assert '"ok": false' in tool_observation.content.lower()
        assert "permission_denied" in tool_observation.content.lower()
        return ModelResponse(
            content="该目录当前未授权，请先在 Desktop Bridge 中授权该目录。",
            provider=self.name,
            model=request.model,
        )


@pytest.mark.asyncio
async def test_non_approval_tool_failure_becomes_model_observation_not_runtime_500():
    provider = _RecoveringProvider("local.fs.list")
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="local.fs.list",
            description="List an authorized local directory.",
            inputSchema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
        ),
        lambda _: (_ for _ in ()).throw(
            ToolError(
                ToolErrorType.PERMISSION_DENIED,
                "desktop bridge denied the requested local operation",
            )
        ),
    )

    events = []
    answer = await ToolLoopRunner(
        ModelGateway(provider, timeout=1, max_retries=0),
        "test",
        registry,
        max_retries=0,
    ).run(
        r"看看 E:\AIProject",
        on_tool_event=events.append,
    )

    assert "未授权" in answer
    assert provider.calls == 2
    titles = [event["title"] for event in events]
    assert "Tool Blocked" in titles
    assert "Tool Completed" not in titles


class _UnavailableProvider:
    name = "unavailable"

    def __init__(self):
        self.calls = 0

    async def generate(self, request):
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                content="",
                provider=self.name,
                model=request.model,
                tool_calls=[
                    ToolCall(
                        id="tool-2",
                        name="local.fs.list",
                        arguments={"path": r"E:\AIProject"},
                    )
                ],
            )
        return ModelResponse(
            content="Desktop Bridge 当前不可用，请确认本机桥接服务已经启动。",
            provider=self.name,
            model=request.model,
        )


@pytest.mark.asyncio
async def test_unavailable_desktop_bridge_is_user_level_failure_not_transport_failure():
    provider = _UnavailableProvider()
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="local.fs.list",
            inputSchema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
        ),
        lambda _: (_ for _ in ()).throw(
            ToolError(
                ToolErrorType.UNAVAILABLE,
                "desktop bridge is unavailable",
            )
        ),
    )

    answer = await ToolLoopRunner(
        ModelGateway(provider, timeout=1, max_retries=0),
        "test",
        registry,
        max_retries=0,
    ).run(r"看看 E:\AIProject")

    assert "不可用" in answer
    assert provider.calls == 2


@pytest.mark.asyncio
async def test_non_desktop_tool_failure_keeps_existing_failure_isolation_semantics():
    class Provider:
        name = "generic-failure"

        async def generate(self, request):
            return ModelResponse(
                content="",
                provider=self.name,
                model=request.model,
                tool_calls=[
                    ToolCall(
                        id="generic-1",
                        name="orders.lookup",
                        arguments={"query": "x"},
                    )
                ],
            )

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="orders.lookup",
            inputSchema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        ),
        lambda _: (_ for _ in ()).throw(
            ToolError(ToolErrorType.UNAVAILABLE, "temporary upstream failure")
        ),
    )

    with pytest.raises(ToolError) as raised:
        await ToolLoopRunner(
            ModelGateway(Provider(), timeout=1, max_retries=0),
            "test",
            registry,
            max_retries=0,
        ).run("查一下订单")

    assert raised.value.error_type == ToolErrorType.UNAVAILABLE
