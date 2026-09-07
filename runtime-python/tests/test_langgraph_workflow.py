import pytest

from app.agents import AgentExecutionRequest
from app.agents.workflows import (
    LangGraphAgentWorkflow,
)
from app.schemas import AgentProfile
from app.services import create_registry
from app.tools import (
    ToolRegistry,
    register_demo_tools,
)


def create_agent() -> AgentProfile:
    return AgentProfile(
        id=100,
        name="LangGraphTestAgent",
        description="test langgraph agent",
        endpoint="internal://langgraph",
        protocol="langgraph",
        capabilities=[
            "general",
            "business",
        ],
        provider="mock",
    )


@pytest.mark.asyncio
async def test_langgraph_model_route():
    runtime_events = []
    registry = await create_registry()

    try:
        model = registry.context.get(
            "model.default"
        )

        workflow = LangGraphAgentWorkflow(
            model
        )

        model_events = []
        tool_events = []

        request = AgentExecutionRequest(
            agent=create_agent(),
            capability="general",
            task="Explain what an AI Agent is.",
            on_model_event=model_events.append,
            on_tool_event=tool_events.append,
            on_runtime_event=runtime_events.append,
        )

        result = await workflow.run(
            request
        )

        assert result

        assert any(
            event["kind"]
            == "model_call_started"
            for event in model_events
        )

        assert any(
            event["kind"]
            == "model_call_completed"
            for event in model_events
        )

        assert not tool_events

        assert any(
            event["title"]
            == "LangGraph Route Selected"
            and event["route"]
            == "model"
            for event in runtime_events
        )

        assert any(
            event["title"]
            == "LangGraph Node Completed"
            and event.get("node")
            == "model_call"
            for event in runtime_events
        )

    finally:
        await registry.stop_all()


@pytest.mark.asyncio
async def test_langgraph_tool_route():
    registry = await create_registry()
    runtime_events = []

    try:
        model = registry.context.get(
            "model.default"
        )

        workflow = LangGraphAgentWorkflow(
            model
        )

        tool_registry = ToolRegistry()

        register_demo_tools(
            tool_registry
        )

        model_events = []
        tool_events = []

        request = AgentExecutionRequest(
            agent=create_agent(),
            capability="business",
            task=(
                "Check the logistics status "
                "for order ORDER20260901001"
            ),
            on_model_event=model_events.append,
            tool_registry=tool_registry,
            on_tool_event=tool_events.append,
            on_runtime_event=runtime_events.append,
        )

        result = await workflow.run(
            request
        )

        assert result

        assert any(
            event["title"]
            == "Tool Selected"
            for event in tool_events
        )

        assert any(
            event["title"]
            == "Tool Completed"
            for event in tool_events
        )

        completed_model_calls = [
            event
            for event in model_events
            if event["kind"]
            == "model_call_completed"
        ]

        assert len(
            completed_model_calls
        ) >= 2

        assert any(
            event["title"]
            == "LangGraph Route Selected"
            and event["route"]
            == "tool"
            for event in runtime_events
        )

        assert any(
            event["title"]
            == "LangGraph Node Completed"
            and event.get("node")
            == "tool_loop"
            for event in runtime_events
        )

    finally:
        await registry.stop_all()