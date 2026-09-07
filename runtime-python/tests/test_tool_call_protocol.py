import json

import pytest

from app.models import (
    ModelResponse,
    ToolCall,
)
from app.models.providers import (
    _serialize_openai_message,
)
from app.models.contracts import (
    ModelMessage,
)
from app.tools import (
    ToolLoopRunner,
    ToolRegistry,
    register_demo_tools,
)


def test_openai_tool_call_message_serialization():
    message = ModelMessage(
        role="assistant",
        content="",
        tool_calls=[
            ToolCall(
                id="call_123",
                name="get_logistics",
                arguments={
                    "query": "ORDER001",
                },
            )
        ],
    )

    payload = _serialize_openai_message(
        message
    )

    assert (
        payload["tool_calls"][0]["id"]
        == "call_123"
    )

    assert (
        payload["tool_calls"][0]
        ["type"]
        == "function"
    )

    function = (
        payload["tool_calls"][0]
        ["function"]
    )

    assert (
        function["name"]
        == "get_logistics"
    )

    assert json.loads(
        function["arguments"]
    ) == {
        "query": "ORDER001"
    }


@pytest.mark.asyncio
async def test_tool_loop_preserves_tool_call_history():
    class CapturingGateway:
        def __init__(self):
            self.requests = []

        async def generate(
            self,
            request,
            on_event=None,
        ):
            self.requests.append(
                request
            )

            if len(self.requests) == 1:
                return ModelResponse(
                    content="",
                    provider="test",
                    model=request.model,
                    finish_reason="tool_calls",
                    tool_calls=[
                        ToolCall(
                            id="call_123",
                            name="get_logistics",
                            arguments={
                                "query": (
                                    "ORDER001"
                                ),
                            },
                        )
                    ],
                )

            return ModelResponse(
                content=(
                    "The logistics status "
                    "is IN_TRANSIT."
                ),
                provider="test",
                model=request.model,
                finish_reason="stop",
            )

    registry = ToolRegistry()

    register_demo_tools(
        registry
    )

    gateway = CapturingGateway()

    result = await ToolLoopRunner(
        gateway,
        "test-model",
        registry,
    ).run(
        "Check logistics "
        "for ORDER001"
    )

    assert (
        result
        == "The logistics status "
        "is IN_TRANSIT."
    )

    assert len(
        gateway.requests
    ) == 2

    second_request = (
        gateway.requests[1]
    )

    assistant_message = next(
        message
        for message
        in second_request.messages
        if message.role == "assistant"
    )

    tool_message = next(
        message
        for message
        in second_request.messages
        if message.role == "tool"
    )

    assert (
        assistant_message
        .tool_calls[0]
        .id
        == "call_123"
    )

    assert (
        tool_message.tool_call_id
        == "call_123"
    )