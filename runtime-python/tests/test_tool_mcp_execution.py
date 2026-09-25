import asyncio

import pytest
from mcp.server import MCPServer

from app.mcp import MCPServerDefinition
from app.models import ModelGateway, ModelResponse, ToolCall
from app.schemas import AgentProfile, RuntimeRequest
from app.services import RuntimeEngine, create_registry
from app.tools import (
    ToolDefinition,
    ToolError,
    ToolErrorType,
    ToolLoopRunner,
    ToolRegistry,
    register_builtin_tools,
)


def run(coro):
    return asyncio.run(coro)


def test_builtin_tools_execute_real_logic():
    registry = ToolRegistry()
    register_builtin_tools(registry)

    calculated = run(
        registry.execute(
            "calculator",
            {"expression": "382 * 927"},
        )
    )
    assert calculated["result"] == 354114

    stats = run(
        registry.execute(
            "text_stats",
            {"text": "hello AgentMesh\nsecond line"},
        )
    )
    assert stats["words"] == 4
    assert stats["lines"] == 2

    current = run(
        registry.execute(
            "current_time",
            {"timezone": "Asia/Shanghai"},
        )
    )
    assert current["timezone"] == "Asia/Shanghai"
    assert "T" in current["iso8601"]


def test_builtin_calculator_is_sandboxed():
    registry = ToolRegistry()
    register_builtin_tools(registry)

    with pytest.raises(ToolError) as raised:
        run(
            registry.execute(
                "calculator",
                {"expression": "__import__('os').system('whoami')"},
            )
        )
    assert raised.value.error_type == ToolErrorType.INVALID_ARGUMENTS


def test_tool_schema_rejects_missing_wrong_and_extra_arguments():
    registry = ToolRegistry()
    register_builtin_tools(registry)

    for arguments in (
        {},
        {"expression": 123},
        {"expression": "1 + 2", "secretExtra": "x"},
    ):
        with pytest.raises(ToolError) as raised:
            run(registry.execute("calculator", arguments))
        assert raised.value.error_type == ToolErrorType.INVALID_ARGUMENTS


def test_tool_loop_retries_transient_failure_and_emits_retry():
    class Provider:
        name = "retry-model"

        def __init__(self):
            self.calls = 0

        async def generate(self, req):
            self.calls += 1
            if self.calls == 1:
                return ModelResponse(
                    content="",
                    provider=self.name,
                    model=req.model,
                    tool_calls=[
                        ToolCall(
                            id="call-1",
                            name="flaky",
                            arguments={"query": "x"},
                        )
                    ],
                )
            return ModelResponse(
                content="done",
                provider=self.name,
                model=req.model,
            )

    attempts = {"count": 0}

    def flaky(_):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise ToolError(ToolErrorType.UNAVAILABLE, "temporary")
        return {"ok": True}

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="flaky",
            inputSchema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        ),
        flaky,
    )
    events = []
    answer = run(
        ToolLoopRunner(
            ModelGateway(Provider(), timeout=1, max_retries=0),
            "retry",
            registry,
            max_retries=1,
            retry_backoff_seconds=0,
        ).run("use flaky", on_tool_event=events.append)
    )

    assert answer == "done"
    assert attempts["count"] == 2
    assert "Tool Retry" in [event["title"] for event in events]
    assert "Tool Completed" in [event["title"] for event in events]



def test_http_tool_adapter_posts_json(monkeypatch):
    captured = {}

    class Response:
        status_code = 200

        def json(self):
            return {"ok": True, "echo": captured["json"]}

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, endpoint, json):
            captured["endpoint"] = endpoint
            captured["json"] = json
            return Response()

    monkeypatch.setattr("app.tools.registry.httpx.AsyncClient", Client)

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="http_echo",
            protocol="http",
            endpoint="http://127.0.0.1:9584/tool/echo",
            inputSchema={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        )
    )

    result = run(registry.execute("http_echo", {"text": "hello"}))
    assert captured["endpoint"].endswith("/tool/echo")
    assert result == {"ok": True, "echo": {"text": "hello"}}

def _mcp_server():
    server = MCPServer("tool-mcp-in-process")

    @server.tool()
    def lookup_weather(city: str) -> dict:
        return {
            "city": city,
            "condition": "sunny",
            "temperatureC": 23,
        }

    return server


def test_runtime_discovers_and_calls_mcp_tool_end_to_end():
    async def scenario():
        registry = await create_registry()
        try:
            server_def = MCPServerDefinition(
                id=44,
                name="Tool/MCP Test Server",
                transport="streamable_http",
                endpoint="http://unused/mcp",
                enabled=True,
            )
            engine = RuntimeEngine(
                registry,
                mcp_targets={44: _mcp_server()},
            )
            agent = AgentProfile(
                id=1,
                name="General",
                endpoint="internal://general",
                protocol="internal",
                capabilities=["general"],
            )

            result = await engine.run(
                RuntimeRequest(
                    user_id=1,
                    request_id="tool-mcp-e2e",
                    task="Use the MCP weather tool to check weather",
                    agents=[agent],
                    mcp_servers=[server_def],
                )
            )

            titles = [event.title for event in result.trace]
            assert "MCP Discovery Completed" in titles
            assert "MCP Call Completed" in titles
            assert "Tool Completed" in titles
            assert result.observability.mcp_events >= 2
            assert result.observability.tool_calls >= 1
        finally:
            await registry.stop_all()

    run(scenario())


def test_runtime_calculator_goes_through_tool_loop():
    async def scenario():
        registry = await create_registry()
        try:
            engine = RuntimeEngine(registry)
            agent = AgentProfile(
                id=1,
                name="General",
                endpoint="internal://general",
                protocol="internal",
                capabilities=["general"],
            )
            result = await engine.run(
                RuntimeRequest(
                    user_id=1,
                    request_id="calculator-tool-e2e",
                    task="请使用 calculator 计算 382 * 927",
                    agents=[agent],
                    tools=[
                        ToolDefinition(
                            id=1,
                            name="calculator",
                            description="calculator",
                            protocol="internal",
                            inputSchema={
                                "type": "object",
                                "properties": {
                                    "expression": {"type": "string"}
                                },
                                "required": ["expression"],
                                "additionalProperties": False,
                            },
                            enabled=True,
                        )
                    ],
                )
            )
            completed = [
                event
                for event in result.trace
                if event.kind == "tool" and event.title == "Tool Completed"
            ]
            assert completed
            assert "354114" in completed[0].detail
        finally:
            await registry.stop_all()

    run(scenario())
