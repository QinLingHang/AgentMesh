from __future__ import annotations

from app.tools.desktop import desktop_screenshot_attachment, desktop_tool_definitions


def test_desktop_agent_tools_have_safe_risk_contracts():
    tools = {tool.name: tool for tool in desktop_tool_definitions()}

    expected_families = {
        "local.fs.",
        "local.app.",
        "local.tool.",
        "local.terminal.",
        "local.ui.",
    }
    for prefix in expected_families:
        assert any(name.startswith(prefix) for name in tools)

    for name in ("local.fs.list", "local.fs.stat", "local.fs.read", "local.fs.search"):
        assert tools[name].risk_level == "low"
        assert tools[name].requires_confirmation is False

    for name in ("local.fs.write", "local.fs.mkdir", "local.fs.copy"):
        assert tools[name].requires_confirmation is True

    for name in (
        "local.fs.move",
        "local.fs.delete",
        "local.app.close",
        "local.tool.run",
        "local.terminal.run",
        "local.ui.session.start",
        "local.ui.window.close",
    ):
        assert tools[name].risk_level == "high"
        assert tools[name].requires_confirmation is True

    # Once an explicit Computer Use session is approved, ordinary pointer/
    # keyboard/UIA steps are session-gated at the bridge rather than requiring
    # one human approval for every click or keystroke.
    assert "waitSeconds" in tools["local.tool.status"].input_schema["properties"]
    assert "waitSeconds" in tools["local.terminal.status"].input_schema["properties"]

    for name in (
        "local.ui.mouse.click",
        "local.ui.keyboard.type",
        "local.ui.element.click",
        "local.ui.element.set_text",
    ):
        assert tools[name].risk_level == "medium"
        assert tools[name].requires_confirmation is False


def test_desktop_screenshot_bytes_are_split_from_tool_metadata():
    attachment, metadata = desktop_screenshot_attachment(
        {
            "mediaType": "image/png",
            "width": 1280,
            "height": 720,
            "imageBase64": "QUJD",
        }
    )

    assert attachment is not None
    assert attachment.media_type == "image/png"
    assert attachment.content_base64 == "QUJD"
    assert "imageBase64" not in metadata
    assert metadata["width"] == 1280

import pytest

from app.models import ModelResponse, ToolCall
from app.tools import ToolLoopRunner, ToolRegistry
from app.tools.contracts import ToolDefinition


@pytest.mark.asyncio
async def test_desktop_screenshot_is_sent_to_next_vision_turn_without_trace_base64():
    class Gateway:
        def __init__(self):
            self.requests = []

        async def generate(self, request, on_event=None):
            self.requests.append(request)
            if len(self.requests) == 1:
                return ModelResponse(
                    content="",
                    provider="test",
                    model=request.model,
                    finish_reason="tool_calls",
                    tool_calls=[
                        ToolCall(
                            id="shot-1",
                            name="local.ui.screen.capture",
                            arguments={"sessionId": "session-1"},
                        )
                    ],
                )
            return ModelResponse(
                content="desktop understood",
                provider="test",
                model=request.model,
                finish_reason="stop",
            )

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="local.ui.screen.capture",
            inputSchema={
                "type": "object",
                "properties": {"sessionId": {"type": "string"}},
                "required": ["sessionId"],
                "additionalProperties": False,
            },
        ),
        lambda _: {
            "mediaType": "image/png",
            "width": 800,
            "height": 600,
            "imageBase64": "QUJD",
        },
    )
    events = []
    gateway = Gateway()

    answer = await ToolLoopRunner(
        gateway,
        "text-model",
        registry,
        vision_model="vision-model",
        desktop_max_iterations=8,
    ).run("look at my desktop", on_tool_event=events.append)

    assert answer == "desktop understood"
    assert len(gateway.requests) == 2
    assert gateway.requests[1].model == "vision-model"
    assert len(gateway.requests[1].attachments) == 1
    assert gateway.requests[1].attachments[0].content_base64 == "QUJD"

    tool_message = next(
        message for message in gateway.requests[1].messages if message.role == "tool"
    )
    assert "imageBase64" not in tool_message.content
    assert "QUJD" not in tool_message.content
    assert all("QUJD" not in str(event) for event in events)


@pytest.mark.asyncio
async def test_desktop_screenshot_without_vision_model_fails_closed_to_metadata_only():
    class Gateway:
        def __init__(self):
            self.requests = []

        async def generate(self, request, on_event=None):
            self.requests.append(request)
            if len(self.requests) == 1:
                return ModelResponse(
                    content="",
                    provider="test",
                    model=request.model,
                    finish_reason="tool_calls",
                    tool_calls=[
                        ToolCall(
                            id="shot-1",
                            name="local.ui.screen.capture",
                            arguments={"sessionId": "session-1"},
                        )
                    ],
                )
            return ModelResponse(
                content="use UI Automation",
                provider="test",
                model=request.model,
                finish_reason="stop",
            )

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="local.ui.screen.capture",
            inputSchema={
                "type": "object",
                "properties": {"sessionId": {"type": "string"}},
                "required": ["sessionId"],
                "additionalProperties": False,
            },
        ),
        lambda _: {
            "mediaType": "image/png",
            "width": 800,
            "height": 600,
            "imageBase64": "QUJD",
        },
    )
    gateway = Gateway()

    answer = await ToolLoopRunner(
        gateway,
        "text-model",
        registry,
        vision_model=None,
        desktop_max_iterations=8,
    ).run("inspect desktop")

    assert answer == "use UI Automation"
    assert len(gateway.requests) == 2
    assert gateway.requests[1].model == "text-model"
    assert gateway.requests[1].attachments == []
    tool_message = next(
        message for message in gateway.requests[1].messages if message.role == "tool"
    )
    assert "visionAvailable" in tool_message.content
    assert "false" in tool_message.content.lower()
    assert "QUJD" not in tool_message.content

from app.tools.desktop import desktop_trace_arguments, desktop_trace_result


def test_desktop_trace_sanitizes_file_content_terminal_command_and_process_output():
    write_args = desktop_trace_arguments(
        "local.fs.write",
        {"path": "E:/safe/a.txt", "content": "TOP-SECRET-CONTENT"},
    )
    assert "TOP-SECRET-CONTENT" not in str(write_args)
    assert "CONTENT" in str(write_args)

    terminal_args = desktop_trace_arguments(
        "local.terminal.run",
        {"command": "echo VERY-SECRET", "cwd": "E:/safe"},
    )
    assert "VERY-SECRET" not in str(terminal_args)
    assert "sha256" in str(terminal_args)

    process_result = desktop_trace_result(
        "local.tool.status",
        {"stdout": "PRIVATE-OUTPUT", "stderr": "PRIVATE-ERROR", "exitCode": 0},
    )
    assert "PRIVATE-OUTPUT" not in str(process_result)
    assert "PRIVATE-ERROR" not in str(process_result)
    assert process_result["stdoutChars"] == len("PRIVATE-OUTPUT")
    assert process_result["stderrChars"] == len("PRIVATE-ERROR")


def test_desktop_trace_redacts_computer_session_capability():
    args = desktop_trace_arguments(
        "local.ui.screen.capture",
        {"sessionId": "super-secret-session"},
    )
    result = desktop_trace_result(
        "local.ui.session.start",
        {"active": True, "sessionId": "super-secret-session", "expiresAt": 123},
    )
    assert args["sessionId"] == "[SESSION]"
    assert result["sessionId"] == "[SESSION]"
    assert "super-secret-session" not in str(args)
    assert "super-secret-session" not in str(result)
