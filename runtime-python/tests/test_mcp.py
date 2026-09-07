import asyncio
import pytest
from mcp import Client
from mcp.server import MCPServer
from mcp.types import CallToolResult, TextContent
from app.mcp import (
    MCPErrorType,
    MCPFailureBackoff,
    MCPManager,
    MCPRuntimeError,
    MCPServerDefinition,
    convert_call_result,
    map_mcp_tool,
    normalize_mcp_error,
)
from app.models import ModelGateway, ModelResponse, ToolCall
from app.tools import ToolError, ToolLoopRunner, ToolRegistry

def run(coro): return asyncio.run(coro)

def server():
    mcp=MCPServer("test")
    @mcp.tool()
    def search(query:str)->dict: return {"query":query,"found":True}
    @mcp.tool()
    def text_tool(value:str)->str: return "text:"+value
    return mcp

def definition(
    id=1,
    name="Alpha",
    endpoint="http://unused/mcp",
):
    return MCPServerDefinition(
        id=id,
        name=name,
        transport="streamable_http",
        endpoint=endpoint,
    )

def test_official_sdk_discovery_mapping_and_collision():
    async def scenario():
        async with MCPManager([definition(1,"Alpha"),definition(2,"Beta")],targets={1:server(),2:server()}) as manager:
            tools=await manager.discover_all()
            assert len(tools)==4 and len({t.name for t in tools})==4
            first=next(t for t in tools if t.mcp_server_id==1 and t.original_tool_name=="search")
            assert first.protocol=="mcp" and first.input_schema["type"]=="object" and first.name.startswith("mcp_1_alpha_")
    run(scenario())

def test_official_sdk_call_structured_text_registry_and_events():
    async def scenario():
        events=[]
        async with MCPManager([definition()],events.append,{1:server()}) as manager:
            tools=await manager.discover_all();registry=ToolRegistry()
            from app.mcp import MCPToolAdapter
            for tool in tools: registry.register(tool,adapter=MCPToolAdapter(manager))
            search=next(t for t in tools if t.original_tool_name=="search")
            text=next(t for t in tools if t.original_tool_name=="text_tool")
            assert "found" in str(await registry.execute(search.name,{"query":"x"}))
            assert await registry.execute(text.name,{"value":"x"}) == {"result":"text:x"}
            assert {e["title"] for e in events}>={"MCP Discovery Started","MCP Discovery Completed","MCP Call Started","MCP Call Completed"}
    run(scenario())

def test_result_conversion_and_error():
    assert convert_call_result(CallToolResult(content=[],structuredContent={"x":1}))=={"x":1}
    assert convert_call_result(CallToolResult(content=[TextContent(text="hello")]))=="hello"
    with pytest.raises(MCPRuntimeError) as raised: convert_call_result(CallToolResult(content=[TextContent(text="bad")],isError=True))
    assert raised.value.error_type==MCPErrorType.CALL_FAILED

def test_task_scope_unknown_tool_and_unreachable(
    monkeypatch,
):
    async def test_unknown_tool():
        async with MCPManager(
            [definition()]
        ) as manager:
            unknown_tool = map_mcp_tool(
                definition(2),
                type(
                    "T",
                    (),
                    {
                        "name": "search",
                        "description": "",
                        "input_schema": {},
                    },
                )(),
            )

            with pytest.raises(
                MCPRuntimeError
            ):
                await manager.call_tool(
                    unknown_tool,
                    {},
                )

    run(test_unknown_tool())

    class FailingClient:
        def __init__(
            self,
            *args,
            **kwargs,
        ):
            pass

        async def __aenter__(self):
            raise ConnectionError(
                "simulated connection refused"
            )

        async def __aexit__(
            self,
            exc_type,
            exc,
            traceback,
        ):
            return None

    monkeypatch.setattr(
        "app.mcp.client.Client",
        FailingClient,
    )

    async def test_unreachable_server():
        server_definition = definition(
            endpoint=(
                "http://unreachable.invalid/mcp"
            ),
        )

        async with MCPManager(
            [server_definition]
        ) as manager:
            with pytest.raises(
                MCPRuntimeError
            ) as raised:
                await manager.discover(
                    server_definition
                )

            assert (
                raised.value.error_type
                == MCPErrorType.CONNECTION_FAILED
            )

    run(test_unreachable_server())

def test_exception_group_normalization_and_failure_isolation():
    grouped=ExceptionGroup("transport",[ConnectionError("refused")])
    assert normalize_mcp_error(grouped,"connect").error_type==MCPErrorType.CONNECTION_FAILED
    async def scenario():
        events=[]
        async with MCPManager([definition(1,"Down"),definition(2,"Good")],events.append,{2:server()}) as manager:
            tools=await manager.discover_all()
            assert len(tools)==2 and all(t.mcp_server_id==2 for t in tools)
            assert any(e["title"]=="MCP Discovery Failed" for e in events)
    run(scenario())

def test_mcp_timeout_cancellation_cleanup():
    mcp=MCPServer("slow")
    @mcp.tool()
    async def slow()->str: await asyncio.sleep(1);return "done"
    async def scenario():
        d=definition();d.call_timeout_ms=1
        manager=MCPManager([d],targets={1:mcp});await manager.__aenter__()
        tools=await manager.discover_all()
        from app.mcp import MCPToolAdapter
        registry=ToolRegistry(timeout=1);registry.register(tools[0],adapter=MCPToolAdapter(manager))
        with pytest.raises(ToolError): await registry.execute(tools[0].name,{})
        await manager.__aexit__(None,None,None)
        assert len(manager.stack._exit_callbacks)==0
    run(scenario())

def test_tool_loop_executes_discovered_mcp_tool():
    class Provider:
        name="m"
        def __init__(self):self.calls=0
        async def generate(self,req):
            self.calls+=1
            if self.calls==1:return ModelResponse(content="",provider="m",model=req.model,tool_calls=[ToolCall(id="1",name=req.tools[0].name,arguments={"query":"weather"})])
            return ModelResponse(content="final",provider="m",model=req.model)
    async def scenario():
        async with MCPManager([definition()],targets={1:server()}) as manager:
            from app.mcp import MCPToolAdapter
            registry=ToolRegistry()
            for tool in await manager.discover_all():
                if tool.original_tool_name=="search":registry.register(tool,adapter=MCPToolAdapter(manager))
            assert await ToolLoopRunner(ModelGateway(Provider(),timeout=1,max_retries=0),"m",registry).run("search") == "final"
    run(scenario())

def test_mcp_failure_backoff_blocks_until_retry_window():
    now = [
        100.0
    ]

    backoff = (
        MCPFailureBackoff(
            base_seconds=30,
            max_seconds=120,
            clock=lambda: now[0],
        )
    )

    d = definition()

    # 初始状态：
    # Server 可以正常尝试 Discovery。
    first = (
        backoff.decision(
            d
        )
    )

    assert (
        first.blocked
        is False
    )

    # 第一次失败：
    # 进入 30 秒 Backoff。
    entry = (
        backoff.record_failure(
            d,
            error_type=(
                "protocol_error"
            ),
            message=(
                "server unavailable"
            ),
        )
    )

    assert (
        entry
        .consecutive_failures
        == 1
    )

    blocked = (
        backoff.decision(
            d
        )
    )

    assert (
        blocked.blocked
        is True
    )

    assert (
        blocked
        .remaining_ms
        == 30000
    )

    assert (
        blocked
        .error_type
        == "protocol_error"
    )

    # 29 秒以后依旧不能 Probe。
    now[0] += 29

    still_blocked = (
        backoff.decision(
            d
        )
    )

    assert (
        still_blocked.blocked
        is True
    )

    # 30 秒窗口到期：
    # 允许重新 Probe。
    now[0] += 1

    retry = (
        backoff.decision(
            d
        )
    )

    assert (
        retry.blocked
        is False
    )


def test_mcp_failure_backoff_exponential_and_success_reset():
    now = [
        500.0
    ]

    backoff = (
        MCPFailureBackoff(
            base_seconds=30,
            max_seconds=120,
            clock=lambda: now[0],
        )
    )

    d = definition()

    # 第一次失败：
    # 30 秒。
    backoff.record_failure(
        d
    )

    now[0] += 30

    assert (
        backoff
        .decision(
            d
        )
        .blocked
        is False
    )

    # 第二次连续失败：
    # Backoff 翻倍为 60 秒。
    second = (
        backoff.record_failure(
            d
        )
    )

    assert (
        second
        .consecutive_failures
        == 2
    )

    decision = (
        backoff.decision(
            d
        )
    )

    assert (
        decision
        .remaining_ms
        == 60000
    )

    # Server 恢复成功后，
    # 整个失败历史清空。
    backoff.record_success(
        d
    )

    recovered = (
        backoff.decision(
            d
        )
    )

    assert (
        recovered.blocked
        is False
    )

    assert (
        recovered
        .consecutive_failures
        == 0
    )

    # 下一次重新失败时，
    # 又从第一次失败 30 秒开始。
    again = (
        backoff.record_failure(
            d
        )
    )

    assert (
        again
        .consecutive_failures
        == 1
    )
