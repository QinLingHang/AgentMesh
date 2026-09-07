import pytest

from app.plugins.schedulers import (
    AdaptiveSchedulerPlugin,
)
from app.schemas import (
    AgentCapabilityProfile,
    AgentProfile,
    RuntimeRequest,
    TaskConstraints,
    TaskProfile,
)
from app.services import (
    RuntimeEngine,
    create_registry,
)


def create_agent(
    agent_id: int,
    name: str,
    endpoint: str,
    *,
    quality: float,
    success: float,
    sample_count: int,
) -> AgentProfile:
    return AgentProfile(
        id=agent_id,
        name=name,
        endpoint=endpoint,
        protocol="internal",
        capabilities=[
            "general"
        ],
        qualityScore=quality,
        successRate=success,
        avgLatencyMs=1000,
        avgCost=0.01,
        status="ACTIVE",
        capabilityProfiles=[
            AgentCapabilityProfile(
                capability="general",
                qualityScore=quality,
                successRate=success,
                failureRate=(
                    1.0 - success
                ),
                avgLatencyMs=1000,
                avgCost=0.01,
                sampleCount=sample_count,
            )
        ],
    )


@pytest.mark.asyncio
async def test_adaptive_explores_less_sampled_agent():
    scheduler = (
        AdaptiveSchedulerPlugin()
    )

    experienced = create_agent(
        1,
        "ExperiencedAgent",
        "internal://experienced",
        quality=0.90,
        success=0.90,
        sample_count=100,
    )

    newcomer = create_agent(
        2,
        "NewAgent",
        "internal://new",
        quality=0.90,
        success=0.90,
        sample_count=0,
    )

    assignments = await scheduler.schedule(
        [
            experienced,
            newcomer,
        ],
        TaskProfile(
            required_capabilities=[
                "general"
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
        == "NewAgent"
    )


@pytest.mark.asyncio
async def test_runtime_can_reschedule_twice():
    registry = await create_registry()

    try:
        engine = RuntimeEngine(
            registry
        )

        agents = [
            create_agent(
                1,
                "PrimaryFail",
                "internal://fail/primary",
                quality=0.99,
                success=0.99,
                sample_count=50,
            ),
            create_agent(
                2,
                "BackupFail",
                "internal://fail/backup",
                quality=0.95,
                success=0.95,
                sample_count=50,
            ),
            create_agent(
                3,
                "BackupSuccess",
                "internal://success",
                quality=0.82,
                success=0.82,
                sample_count=50,
            ),
        ]

        result = await engine.run(
            RuntimeRequest(
                user_id=1,
                request_id=(
                    "double-reschedule-test"
                ),
                task=(
                    "Explain what an "
                    "AI Agent is."
                ),
                scheduler="fixed",
                agents=agents,
            )
        )

        assert len(
            result.agent_feedback
        ) == 3

        assert (
            result.agent_feedback[0]
            .success
            is False
        )

        assert (
            result.agent_feedback[1]
            .success
            is False
        )

        assert (
            result.agent_feedback[2]
            .success
            is True
        )

        completed_reschedules = [
            event
            for event in result.trace
            if (
                event.kind
                == "reschedule"
                and event.status
                == "completed"
            )
        ]

        assert (
            len(
                completed_reschedules
            )
            == 2
        )

        assert (
            "BackupSuccess"
            in result.selected_agents
        )

    finally:
        await registry.stop_all()