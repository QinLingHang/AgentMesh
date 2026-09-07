from types import (
    SimpleNamespace,
)

import pytest

import app.agents.a2a_discovery as discovery_module


from app.agents import (
    A2ACapabilityDiscovery,
)

from app.schemas import (
    AgentCapabilityProfile,
    AgentProfile,
)


class FakeResolver:
    calls = 0

    def __init__(
        self,
        httpx_client,
        base_url,
        **kwargs,
    ):
        self.httpx_client = (
            httpx_client
        )

        self.base_url = (
            base_url
        )

    async def get_agent_card(
        self,
    ):
        type(self).calls += 1

        return SimpleNamespace(
            name=(
                "Remote Test Agent"
            ),

            version="1.0.0",

            skills=[
                SimpleNamespace(
                    id="general",
                    name="General",
                ),

                SimpleNamespace(
                    id="document",
                    name="Document",
                ),
            ],
        )


def make_agent(
    *,
    capabilities=None,
    profiles=None,
) -> AgentProfile:

    return AgentProfile(
        id=1001,

        name=(
            "A2ATestAgent"
        ),

        endpoint=(
            "http://a2a.test"
        ),

        protocol="a2a",

        capabilities=(
            capabilities
            if capabilities
            is not None
            else []
        ),

        capability_profiles=(
            profiles
            if profiles
            is not None
            else []
        ),

        quality_score=0.82,

        avg_latency_ms=1200,

        avg_cost=0.01,

        success_rate=0.95,

        failure_rate=0.05,
    )


@pytest.mark.asyncio
async def test_a2a_discovery_reads_agent_card_skills(
    monkeypatch,
):
    FakeResolver.calls = 0

    monkeypatch.setattr(
        discovery_module,
        "A2ACardResolver",
        FakeResolver,
    )

    discovery = (
        A2ACapabilityDiscovery(
            cache_ttl_seconds=60,
        )
    )

    result = (
        await discovery.discover(
            make_agent()
        )
    )

    assert (
        result.remote_name
        == "Remote Test Agent"
    )

    assert (
        result.remote_version
        == "1.0.0"
    )

    assert (
        result.capabilities
        == (
            "general",
            "document",
        )
    )

    assert (
        result.skill_count
        == 2
    )

    assert (
        result.cache_hit
        is False
    )


@pytest.mark.asyncio
async def test_a2a_discovery_uses_cache(
    monkeypatch,
):
    FakeResolver.calls = 0

    monkeypatch.setattr(
        discovery_module,
        "A2ACardResolver",
        FakeResolver,
    )

    discovery = (
        A2ACapabilityDiscovery(
            cache_ttl_seconds=60,
        )
    )

    agent = (
        make_agent()
    )

    first = (
        await discovery.discover(
            agent
        )
    )

    second = (
        await discovery.discover(
            agent
        )
    )

    assert (
        first.cache_hit
        is False
    )

    assert (
        second.cache_hit
        is True
    )

    assert (
        FakeResolver.calls
        == 1
    )


@pytest.mark.asyncio
async def test_a2a_discovery_hydrates_agent_capabilities(
    monkeypatch,
):
    FakeResolver.calls = 0

    monkeypatch.setattr(
        discovery_module,
        "A2ACardResolver",
        FakeResolver,
    )

    agent = (
        make_agent(
            capabilities=[
                "general"
            ]
        )
    )

    discovery = (
        A2ACapabilityDiscovery(
            cache_ttl_seconds=60,
        )
    )

    result = (
        await discovery.hydrate(
            agent
        )
    )

    assert (
        agent.capabilities
        == [
            "general",
            "document",
        ]
    )

    assert (
        result
        .added_capabilities
        == (
            "document",
        )
    )

    profiles = {
        item.capability:
            item

        for item
        in agent
        .capability_profiles
    }

    assert (
        set(
            profiles
        )
        == {
            "general",
            "document",
        }
    )

    assert (
        profiles[
            "document"
        ]
        .quality_score
        == pytest.approx(
            0.82
        )
    )

    assert (
        profiles[
            "document"
        ]
        .sample_count
        == 0
    )


@pytest.mark.asyncio
async def test_a2a_discovery_preserves_historical_profile(
    monkeypatch,
):
    FakeResolver.calls = 0

    monkeypatch.setattr(
        discovery_module,
        "A2ACardResolver",
        FakeResolver,
    )

    historical = (
        AgentCapabilityProfile(
            capability="general",

            quality_score=0.96,

            avg_latency_ms=400,

            avg_cost=0.03,

            success_rate=0.99,

            failure_rate=0.01,

            sample_count=88,
        )
    )

    agent = (
        make_agent(
            capabilities=[
                "general"
            ],

            profiles=[
                historical
            ],
        )
    )

    discovery = (
        A2ACapabilityDiscovery()
    )

    await discovery.hydrate(
        agent
    )

    general = next(
        item
        for item
        in agent
        .capability_profiles
        if (
            item.capability
            == "general"
        )
    )

    document = next(
        item
        for item
        in agent
        .capability_profiles
        if (
            item.capability
            == "document"
        )
    )

    # Historical Runtime feedback preserved.
    assert (
        general
        .quality_score
        == pytest.approx(
            0.96
        )
    )

    assert (
        general
        .sample_count
        == 88
    )

    # New capability gets baseline.
    assert (
        document
        .quality_score
        == pytest.approx(
            0.82
        )
    )

    assert (
        document
        .sample_count
        == 0
    )