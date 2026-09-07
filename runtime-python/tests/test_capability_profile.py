import pytest

from app.agents.capability import (
    apply_capability_feedback,
)
from app.plugins.schedulers import (
    GreedySchedulerPlugin,
)
from app.schemas import (
    AgentCapabilityProfile,
    AgentFeedback,
    AgentProfile,
    RuntimeRequest,
    TaskConstraints,
    TaskProfile,
)
from app.services import (
    RuntimeEngine,
    create_registry,
)


def agent(
    agent_id: int,
    name: str,
    *,
    overall_quality: float,
    business_quality: float,
    business_success: float,
) -> AgentProfile:
    return AgentProfile(
        id=agent_id,
        name=name,
        endpoint="internal://test",
        protocol="internal",
        capabilities=[
            "business",
        ],
        qualityScore=overall_quality,
        successRate=overall_quality,
        avgLatencyMs=1000,
        avgCost=0.01,
        capabilityProfiles=[
            AgentCapabilityProfile(
                capability="business",
                qualityScore=(
                    business_quality
                ),
                successRate=(
                    business_success
                ),
                failureRate=(
                    1.0
                    - business_success
                ),
                avgLatencyMs=1000,
                avgCost=0.01,
                sampleCount=20,
            )
        ],
    )


@pytest.mark.asyncio
async def test_greedy_uses_capability_profile():
    scheduler = (
        GreedySchedulerPlugin()
    )

    overall_strong_but_business_weak = (
        agent(
            1,
            "AgentA",
            overall_quality=0.98,
            business_quality=0.30,
            business_success=0.40,
        )
    )

    overall_weaker_but_business_strong = (
        agent(
            2,
            "AgentB",
            overall_quality=0.70,
            business_quality=0.95,
            business_success=0.98,
        )
    )

    assignments = await scheduler.schedule(
        [
            overall_strong_but_business_weak,
            overall_weaker_but_business_strong,
        ],
        TaskProfile(
            required_capabilities=[
                "business"
            ],
            complexity="low",
            risk_level="low",
            modality=[
                "text"
            ],
            parallelizable=False,
        ),
        TaskConstraints(),
    )

    assert (
        assignments[0].agent_name
        == "AgentB"
    )


def test_feedback_updates_only_target_capability():
    target = AgentProfile(
        id=1,
        name="AgentA",
        endpoint="internal://test",
        protocol="internal",
        capabilities=[
            "business",
            "diagnostic",
        ],
        capabilityProfiles=[
            AgentCapabilityProfile(
                capability="business",
                qualityScore=0.9,
                successRate=0.8,
                failureRate=0.2,
                avgLatencyMs=1000,
                avgCost=0.01,
                sampleCount=10,
            ),
            AgentCapabilityProfile(
                capability="diagnostic",
                qualityScore=0.7,
                successRate=0.7,
                failureRate=0.3,
                avgLatencyMs=2000,
                avgCost=0.02,
                sampleCount=5,
            ),
        ],
    )

    diagnostic_before = (
        target.capability_profiles[1]
        .model_copy(deep=True)
    )

    updated = apply_capability_feedback(
        target,
        AgentFeedback(
            agentId=1,
            capability="business",
            success=False,
            latencyMs=3000,
            cost=0.02,
            errorType="TimeoutError",
        ),
    )

    assert updated.sample_count == 11

    assert (
        updated.success_rate
        == 0.64
    )

    assert (
        updated.failure_rate
        == 0.36
    )

    assert (
        updated.avg_latency_ms
        == 1400
    )

    assert (
        updated.avg_cost
        == 0.012
    )

    assert (
        target.capability_profiles[1]
        == diagnostic_before
    )


@pytest.mark.asyncio
async def test_runtime_emits_capability_profile_update():
    registry = await create_registry()

    try:
        engine = RuntimeEngine(
            registry
        )

        result = await engine.run(
            RuntimeRequest(
                user_id=1,
                request_id=(
                    "capability-profile-test"
                ),
                task=(
                    "Explain an AI Agent."
                ),
                scheduler="fixed",
                agents=[
                    AgentProfile(
                        id=10,
                        name="GeneralAgent",
                        endpoint=(
                            "internal://general"
                        ),
                        protocol="internal",
                        capabilities=[
                            "general"
                        ],
                    )
                ],
            )
        )

        assert any(
            item.kind
            == "profile_update"
            and item.title
            == "Capability Profile Updated"
            for item in result.trace
        )

        assert (
            result.agent_feedback[0]
            .capability
            == "general"
        )

        assert (
            result.agent_feedback[0]
            .success
            is True
        )

    finally:
        await registry.stop_all()