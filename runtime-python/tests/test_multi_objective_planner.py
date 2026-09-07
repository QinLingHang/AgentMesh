from app.schemas import (
    AgentCapabilityProfile,
    AgentProfile,
    Assignment,
    TaskConstraints,
    TaskProfile,
)
from app.services.collaboration_planner import (
    MultiObjectiveCollaborationPlanner,
)


def create_agent(
    agent_id: int,
    name: str,
    capability: str,
    *,
    quality: float = 0.90,
    success: float = 0.95,
    latency: int = 1000,
    cost: float = 0.01,
    load: float = 0.1,
) -> AgentProfile:
    return AgentProfile(
        id=agent_id,
        name=name,
        endpoint=(
            f"internal://{name}"
        ),
        protocol="internal",
        capabilities=[
            capability
        ],
        currentLoad=load,
        capabilityProfiles=[
            AgentCapabilityProfile(
                capability=capability,
                qualityScore=quality,
                successRate=success,
                failureRate=(
                    1.0 - success
                ),
                avgLatencyMs=latency,
                avgCost=cost,
                sampleCount=20,
            )
        ],
    )


def create_profile(
    *,
    risk: str = "low",
    parallelizable: bool = True,
) -> TaskProfile:
    return TaskProfile(
        required_capabilities=[
            "business",
            "data",
        ],
        complexity="medium",
        risk_level=risk,
        modality=[
            "text"
        ],
        parallelizable=(
            parallelizable
        ),
    )


def assignments():
    return [
        Assignment(
            capability="business",
            agent_id=1,
            agent_name="BusinessAgent",
        ),
        Assignment(
            capability="data",
            agent_id=2,
            agent_name="DataAgent",
        ),
    ]


def agents():
    return [
        create_agent(
            1,
            "BusinessAgent",
            "business",
            latency=3000,
        ),
        create_agent(
            2,
            "DataAgent",
            "data",
            latency=3000,
        ),
    ]


def test_multi_objective_prefers_parallel_when_latency_matters():
    planner = (
        MultiObjectiveCollaborationPlanner()
    )

    plan = planner.plan(
        assignments=assignments(),
        agents=agents(),
        profile=create_profile(
            risk="low"
        ),
        constraints=(
            TaskConstraints(
                maxLatencyMs=4000,
                maxCost=0.1,
                minQuality=0.8,
            )
        ),
        requested_mode="auto",
    )

    assert (
        plan.topology
        == "parallel"
    )

    assert (
        plan.estimated_latency_ms
        == 3000
    )

    assert (
        plan.utility_score
        > 0
    )


def test_sequential_has_higher_quality_estimate():
    planner = (
        MultiObjectiveCollaborationPlanner()
    )

    sequential = planner.plan(
        assignments=assignments(),
        agents=agents(),
        profile=create_profile(),
        constraints=(
            TaskConstraints(
                maxLatencyMs=10000,
                maxCost=0.1,
                minQuality=0.8,
            )
        ),
        requested_mode=(
            "sequential"
        ),
    )

    parallel = planner.plan(
        assignments=assignments(),
        agents=agents(),
        profile=create_profile(),
        constraints=(
            TaskConstraints(
                maxLatencyMs=10000,
                maxCost=0.1,
                minQuality=0.8,
            )
        ),
        requested_mode=(
            "parallel"
        ),
    )

    assert (
        sequential
        .estimated_quality
        >
        parallel
        .estimated_quality
    )


def test_high_risk_penalizes_parallel():
    planner = (
        MultiObjectiveCollaborationPlanner()
    )

    sequential = planner.plan(
        assignments=assignments(),
        agents=agents(),
        profile=create_profile(
            risk="high"
        ),
        constraints=(
            TaskConstraints(
                maxLatencyMs=10000,
                maxCost=0.1,
                minQuality=0.8,
            )
        ),
        requested_mode=(
            "sequential"
        ),
    )

    parallel = planner.plan(
        assignments=assignments(),
        agents=agents(),
        profile=create_profile(
            risk="high"
        ),
        constraints=(
            TaskConstraints(
                maxLatencyMs=10000,
                maxCost=0.1,
                minQuality=0.8,
            )
        ),
        requested_mode=(
            "parallel"
        ),
    )

    assert (
        parallel.utility_score
        <
        sequential.utility_score
    )


def test_constraint_violation_detected():
    planner = (
        MultiObjectiveCollaborationPlanner()
    )

    plan = planner.plan(
        assignments=assignments(),
        agents=agents(),
        profile=create_profile(),
        constraints=(
            TaskConstraints(
                maxLatencyMs=1000,
                maxCost=0.005,
                minQuality=0.99,
            )
        ),
        requested_mode=(
            "parallel"
        ),
    )

    assert (
        plan.constraint_violation
        > 0
    )


def test_single_agent_returns_single_topology():
    planner = (
        MultiObjectiveCollaborationPlanner()
    )

    one_agent = [
        create_agent(
            1,
            "GeneralAgent",
            "general",
        )
    ]

    one_assignment = [
        Assignment(
            capability="general",
            agent_id=1,
            agent_name="GeneralAgent",
        )
    ]

    plan = planner.plan(
        assignments=(
            one_assignment
        ),
        agents=one_agent,
        profile=TaskProfile(
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
        constraints=(
            TaskConstraints()
        ),
        requested_mode="auto",
    )

    assert (
        plan.topology
        == "single"
    )

    assert (
        plan.requires_synthesis
        is False
    )