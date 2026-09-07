import pytest

from app.agents.capability import (
    apply_capability_feedback,
)
from app.eval import (
    EvaluationRequest,
    HeuristicEvaluator,
)
from app.schemas import (
    AgentCapabilityProfile,
    AgentFeedback,
    AgentProfile,
)


@pytest.mark.asyncio
async def test_heuristic_evaluator_returns_quality():
    evaluator = (
        HeuristicEvaluator()
    )

    result = await evaluator.evaluate(
        EvaluationRequest(
            task=(
                "Check order logistics "
                "status."
            ),
            capability="business",
            result=(
                "The order logistics "
                "status is IN_TRANSIT "
                "and the ETA is tomorrow."
            ),
            agent_name=(
                "BusinessAgent"
            ),
        )
    )

    assert (
        0.0
        <= result.quality_score
        <= 1.0
    )

    assert (
        result.evaluator
        == "heuristic"
    )


@pytest.mark.asyncio
async def test_empty_result_has_zero_quality():
    evaluator = (
        HeuristicEvaluator()
    )

    result = await evaluator.evaluate(
        EvaluationRequest(
            task="test",
            capability="general",
            result="",
            agent_name="Agent",
        )
    )

    assert (
        result.quality_score
        == 0.0
    )


def test_quality_feedback_updates_profile():
    agent = AgentProfile(
        id=1,
        name="Agent",
        endpoint=(
            "internal://agent"
        ),
        protocol="internal",
        capabilities=[
            "general"
        ],
        capabilityProfiles=[
            AgentCapabilityProfile(
                capability="general",
                qualityScore=0.5,
                successRate=1.0,
                failureRate=0.0,
                avgLatencyMs=1000,
                avgCost=0.0,
                sampleCount=10,
            )
        ],
    )

    updated = (
        apply_capability_feedback(
            agent,
            AgentFeedback(
                agentId=1,
                capability="general",
                success=True,
                latencyMs=1000,
                cost=0.0,
                qualityScore=1.0,
            ),
        )
    )

    # alpha = 0.2
    #
    # 0.8 * 0.5 + 0.2 * 1
    # = 0.6
    assert (
        updated.quality_score
        == 0.6
    )

    assert (
        updated.sample_count
        == 11
    )


def test_failure_does_not_change_quality():
    agent = AgentProfile(
        id=1,
        name="Agent",
        endpoint=(
            "internal://agent"
        ),
        protocol="internal",
        capabilities=[
            "general"
        ],
        capabilityProfiles=[
            AgentCapabilityProfile(
                capability="general",
                qualityScore=0.8,
                successRate=1.0,
                failureRate=0.0,
                avgLatencyMs=1000,
                avgCost=0.0,
                sampleCount=10,
            )
        ],
    )

    updated = (
        apply_capability_feedback(
            agent,
            AgentFeedback(
                agentId=1,
                capability="general",
                success=False,
                latencyMs=3000,
                cost=0.0,
                errorType=(
                    "TimeoutError"
                ),
            ),
        )
    )

    assert (
        updated.quality_score
        == 0.8
    )