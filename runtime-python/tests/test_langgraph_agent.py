import pytest

from app.agents import (
    AgentExecutor,
    AgentExecutorResolver,
)
from app.schemas import (
    AgentProfile,
    RuntimeRequest,
)
from app.services import (
    RuntimeEngine,
    create_registry,
)


def create_langgraph_agent() -> AgentProfile:
    return AgentProfile(
        id=200,
        name="LangGraphGeneralAgent",
        description=(
            "General purpose "
            "LangGraph Agent"
        ),
        endpoint="langgraph://general",
        protocol="langgraph",
        capabilities=[
            "general",
        ],
        provider="mock",
    )


@pytest.mark.asyncio
async def test_langgraph_plugin_registered():
    registry = await create_registry()

    try:
        resolver = AgentExecutorResolver(
            registry
        )

        executor = resolver.resolve(
            "langgraph"
        )

        assert isinstance(
            executor,
            AgentExecutor,
        )

        assert (
            executor.manifest.id
            == "agent.langgraph"
        )

    finally:
        await registry.stop_all()


@pytest.mark.asyncio
async def test_runtime_executes_langgraph_agent():
    registry = await create_registry()

    try:
        engine = RuntimeEngine(
            registry
        )

        request = RuntimeRequest(
            user_id=1,
            request_id=(
                "req-langgraph-integration"
            ),
            task=(
                "Explain what an AI Agent is."
            ),
            scheduler="greedy",
            agents=[
                create_langgraph_agent()
            ],
        )

        result = await engine.run(
            request
        )

        assert result.answer

        assert (
            "LangGraphGeneralAgent"
            in result.selected_agents
        )

        assert any(
            event.kind == "agent"
            and event.title
            == "LangGraphGeneralAgent started"
            for event in result.trace
        )

        assert any(
            event.kind == "agent"
            and event.title
            == "LangGraphGeneralAgent completed"
            for event in result.trace
        )

        assert any(
            event.kind == "model"
            and event.title
            == "Model Call Started"
            for event in result.trace
        )

        assert any(
            event.kind == "model"
            and event.title
            == "Model Call Completed"
            for event in result.trace
        )
        assert any(
            event.kind == "langgraph"
            and event.title
            == "LangGraph Node Started"
            for event in result.trace
        )

        assert any(
            event.kind == "langgraph"
            and event.title
            == "LangGraph Route Selected"
            for event in result.trace
        )

        assert any(
            event.kind == "langgraph"
            and event.title
            == "LangGraph Node Completed"
            for event in result.trace
        )

    finally:
        await registry.stop_all()