import asyncio

import pytest
from mcp.server import MCPServer

from app.mcp import MCPManager, MCPServerDefinition
from app.schemas import AgentProfile, RuntimeContinuation, RuntimeRequest
from app.services import RuntimeEngine, create_registry
from app.tools import ToolApprovalRequest, ToolApprovalRequired, ToolDefinition, ToolRegistry
from app.tools.approval import tool_call_fingerprint
from app.tools.registry import HTTPToolAdapter


def run(coro):
    return asyncio.run(coro)


def agent() -> AgentProfile:
    return AgentProfile(
        id=1,
        name="General",
        endpoint="internal://general",
        protocol="internal",
        capabilities=["general"],
    )


def approval_continuation(tool: ToolDefinition, arguments: dict) -> RuntimeContinuation:
    approval = ToolApprovalRequest.create(tool, arguments)
    return RuntimeContinuation(
        protocol="tool_approval",
        agentId=1,
        capability="general",
        taskId=approval.approval_id,
        contextId=approval.fingerprint,
        state="AUTH_REQUIRED",
        kind="tool_approval",
        approvalId=approval.approval_id,
        toolName=approval.tool_name,
        toolProtocol=approval.protocol,
        riskLevel=approval.risk_level,
        requiresConfirmation=approval.requires_confirmation,
        arguments=approval.arguments,
        fingerprint=approval.fingerprint,
        summary=approval.summary,
    )


def test_explicit_confirmation_suspends_even_for_low_risk_tool():
    registry = ToolRegistry()
    executed = []
    tool = ToolDefinition(
        id=7,
        name="confirm_me",
        riskLevel="low",
        requiresConfirmation=True,
        inputSchema={"type": "object"},
    )
    registry.register(tool, lambda arguments: executed.append(arguments))

    with pytest.raises(Exception) as raised:
        run(registry.execute("confirm_me", {}))

    # Registry is the final governance boundary: explicit confirmation must not
    # execute until an approval grant is supplied.
    assert "approval" in str(raised.value).lower() or "confirm" in str(raised.value).lower()
    assert executed == []


def test_approval_preview_redacts_nested_secret_values():
    tool = ToolDefinition(id=9, name="dangerous", riskLevel="high")
    approval = ToolApprovalRequest.create(
        tool,
        {
            "order_id": "ORDER-1",
            "password": "secret-value",
            "nested": {"token": "abc", "note": "credential: hidden"},
            "items": [{"otp": "654321"}, "bearer very-secret"],
        },
    )
    preview = approval.safe_arguments()
    assert preview["order_id"] == "ORDER-1"
    assert preview["password"] == "[REDACTED]"
    assert preview["nested"]["token"] == "[REDACTED]"
    assert preview["nested"]["note"] == "[REDACTED]"
    assert preview["items"][0]["otp"] == "[REDACTED]"
    assert preview["items"][1] == "[REDACTED]"
    assert "secret-value" not in str(preview)
    assert "654321" not in str(preview)


def test_fingerprint_binds_tool_configuration_and_exact_arguments():
    tool = ToolDefinition(
        id=10,
        name="cancel_order",
        protocol="http",
        endpoint="http://127.0.0.1:9000/cancel",
        riskLevel="high",
        requiresConfirmation=True,
    )
    baseline = tool_call_fingerprint(tool, {"order_id": "ORDER-1"})
    changed_args = tool_call_fingerprint(tool, {"order_id": "ORDER-2"})
    changed_tool = tool.model_copy(update={"endpoint": "http://127.0.0.1:9001/cancel"})
    changed_config = tool_call_fingerprint(changed_tool, {"order_id": "ORDER-1"})
    assert baseline != changed_args
    assert baseline != changed_config


def test_reject_path_completes_without_tool_execution(monkeypatch):
    calls = []

    async def should_not_execute(self, tool, arguments, timeout):
        calls.append(arguments)
        return {"ok": True}

    monkeypatch.setattr(HTTPToolAdapter, "execute", should_not_execute)
    tool = ToolDefinition(
        id=11,
        name="cancel_order",
        protocol="http",
        endpoint="http://fixture/cancel",
        riskLevel="high",
        requiresConfirmation=True,
        inputSchema={"type": "object"},
    )

    async def scenario():
        registry = await create_registry()
        try:
            result = await RuntimeEngine(registry).run(
                RuntimeRequest(
                    user_id=1,
                    request_id="secure-action-reject",
                    task="reject",
                    agents=[agent()],
                    tools=[tool],
                    continuation=approval_continuation(tool, {"order_id": "ORDER-1"}),
                )
            )
            return result
        finally:
            await registry.stop_all()

    result = run(scenario())
    assert result.status == "COMPLETED"
    assert calls == []
    assert "取消" in result.answer
    assert "Approval Rejected" in [event.title for event in result.trace]


def test_approve_executes_exact_persisted_action_once_without_retry(monkeypatch):
    calls = []

    async def execute(self, tool, arguments, timeout):
        calls.append(dict(arguments))
        return {"status": "CANCELED", "order_id": arguments["order_id"]}

    monkeypatch.setattr(HTTPToolAdapter, "execute", execute)
    tool = ToolDefinition(
        id=12,
        name="cancel_order",
        protocol="http",
        endpoint="http://fixture/cancel",
        riskLevel="high",
        requiresConfirmation=True,
        inputSchema={
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
            "additionalProperties": False,
        },
    )

    async def scenario():
        registry = await create_registry()
        try:
            return await RuntimeEngine(registry).run(
                RuntimeRequest(
                    user_id=1,
                    request_id="secure-action-approve",
                    task="approve",
                    agents=[agent()],
                    tools=[tool],
                    continuation=approval_continuation(tool, {"order_id": "ORDER-1"}),
                )
            )
        finally:
            await registry.stop_all()

    result = run(scenario())
    assert calls == [{"order_id": "ORDER-1"}]
    assert result.status == "COMPLETED"
    titles = [event.title for event in result.trace]
    assert "Approval Granted" in titles
    assert "Tool Completed" in titles


def test_approved_action_failure_is_not_retried(monkeypatch):
    calls = []

    async def fail_once(self, tool, arguments, timeout):
        calls.append(dict(arguments))
        raise RuntimeError("ambiguous transport failure")

    monkeypatch.setattr(HTTPToolAdapter, "execute", fail_once)
    tool = ToolDefinition(
        id=13,
        name="refund_order",
        protocol="http",
        endpoint="http://fixture/refund",
        riskLevel="high",
        requiresConfirmation=True,
        inputSchema={"type": "object"},
    )

    async def scenario():
        registry = await create_registry()
        try:
            with pytest.raises(RuntimeError, match="ambiguous transport failure"):
                await RuntimeEngine(registry).run(
                    RuntimeRequest(
                        user_id=1,
                        request_id="secure-action-no-retry",
                        task="approve",
                        agents=[agent()],
                        tools=[tool],
                        continuation=approval_continuation(tool, {"order_id": "ORDER-1"}),
                    )
                )
        finally:
            await registry.stop_all()

    run(scenario())
    assert calls == [{"order_id": "ORDER-1"}]


def test_fingerprint_mismatch_fails_closed_before_execution(monkeypatch):
    calls = []

    async def execute(self, tool, arguments, timeout):
        calls.append(dict(arguments))
        return {"ok": True}

    monkeypatch.setattr(HTTPToolAdapter, "execute", execute)
    approved_tool = ToolDefinition(
        id=14,
        name="cancel_order",
        protocol="http",
        endpoint="http://fixture/original",
        riskLevel="high",
        requiresConfirmation=True,
    )
    changed_tool = approved_tool.model_copy(update={"endpoint": "http://fixture/changed"})
    continuation = approval_continuation(approved_tool, {"order_id": "ORDER-1"})

    async def scenario():
        registry = await create_registry()
        try:
            with pytest.raises(RuntimeError, match="no longer matches"):
                await RuntimeEngine(registry).run(
                    RuntimeRequest(
                        user_id=1,
                        request_id="secure-action-fingerprint",
                        task="approve",
                        agents=[agent()],
                        tools=[changed_tool],
                        continuation=continuation,
                    )
                )
        finally:
            await registry.stop_all()

    run(scenario())
    assert calls == []


def _mcp_server(counter):
    server = MCPServer("secure-action-in-process")

    @server.tool()
    def cancel_order(order_id: str) -> dict:
        counter.append(order_id)
        return {"orderId": order_id, "status": "CANCELED"}

    return server


def test_mcp_destructive_action_requires_and_honors_exact_approval():
    async def scenario():
        calls = []
        server_def = MCPServerDefinition(
            id=55,
            name="Secure Action MCP",
            transport="streamable_http",
            endpoint="http://unused/mcp",
            enabled=True,
        )
        server = _mcp_server(calls)

        async with MCPManager([server_def], targets={55: server}) as manager:
            discovered = await manager.discover_all()
        tool = next(item for item in discovered if item.original_tool_name == "cancel_order")
        assert tool.risk_level == "high"
        assert tool.requires_confirmation is True

        registry = await create_registry()
        try:
            result = await RuntimeEngine(registry, mcp_targets={55: server}).run(
                RuntimeRequest(
                    user_id=1,
                    request_id="secure-action-mcp-approve",
                    task="approve",
                    agents=[agent()],
                    mcp_servers=[server_def],
                    continuation=approval_continuation(tool, {"order_id": "ORDER-9"}),
                )
            )
        finally:
            await registry.stop_all()

        assert calls == ["ORDER-9"]
        assert result.status == "COMPLETED"
        assert "Approval Granted" in [event.title for event in result.trace]
        assert "MCP Call Completed" in [event.title for event in result.trace]

    run(scenario())
