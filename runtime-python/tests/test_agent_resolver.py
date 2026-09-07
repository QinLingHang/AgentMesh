import pytest

from app.agents import (
    AgentExecutor,
    AgentExecutorResolutionError,
    AgentExecutorResolver,
)
from app.services import create_registry


@pytest.mark.asyncio
async def test_resolve_internal_and_http_agent_executors():
    registry = await create_registry()

    try:
        resolver = AgentExecutorResolver(registry)

        internal_executor = resolver.resolve("internal")
        http_executor = resolver.resolve("HTTP")

        assert isinstance(
            internal_executor,
            AgentExecutor,
        )

        assert isinstance(
            http_executor,
            AgentExecutor,
        )

        assert (
            internal_executor.manifest.id
            == "agent.internal"
        )

        assert (
            http_executor.manifest.id
            == "agent.http"
        )

    finally:
        await registry.stop_all()


@pytest.mark.asyncio
async def test_resolve_unknown_agent_protocol():
    registry = await create_registry()

    try:
        resolver = AgentExecutorResolver(registry)

        with pytest.raises(
            AgentExecutorResolutionError,
            match="unsupported agent protocol",
        ):
            resolver.resolve(
                "not-registered"
            )

    finally:
        await registry.stop_all()