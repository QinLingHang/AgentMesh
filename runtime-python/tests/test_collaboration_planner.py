from app.schemas import (
    Assignment,
    TaskConstraints,
    TaskProfile,
)
from app.services.collaboration_planner import (
    CollaborationPlanner,
)


def assignment(
    index: int,
    capability: str,
) -> Assignment:
    return Assignment(
        capability=capability,
        agent_id=index,
        agent_name=(
            f"Agent{index}"
        ),
    )


def profile(
    *,
    capabilities: list[str],
    parallelizable: bool,
    risk: str = "low",
) -> TaskProfile:
    return TaskProfile(
        required_capabilities=(
            capabilities
        ),
        complexity="low",
        risk_level=risk,
        modality=[
            "text"
        ],
        parallelizable=(
            parallelizable
        ),
    )


def test_single_agent_plan():
    planner = (
        CollaborationPlanner()
    )

    plan = planner.plan(
        assignments=[
            assignment(
                1,
                "general",
            )
        ],
        profile=profile(
            capabilities=[
                "general"
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
        plan.max_parallelism
        == 1
    )

    assert (
        plan.requires_synthesis
        is False
    )


def test_auto_parallel_plan():
    planner = (
        CollaborationPlanner()
    )

    plan = planner.plan(
        assignments=[
            assignment(
                1,
                "business",
            ),
            assignment(
                2,
                "data",
            ),
        ],
        profile=profile(
            capabilities=[
                "business",
                "data",
            ],
            parallelizable=True,
        ),
        constraints=(
            TaskConstraints()
        ),
        requested_mode="auto",
    )

    assert (
        plan.topology
        == "parallel"
    )

    assert (
        plan.max_parallelism
        == 2
    )

    assert (
        plan.requires_synthesis
        is True
    )


def test_high_risk_prefers_sequential():
    planner = (
        CollaborationPlanner()
    )

    plan = planner.plan(
        assignments=[
            assignment(
                1,
                "business",
            ),
            assignment(
                2,
                "data",
            ),
        ],
        profile=profile(
            capabilities=[
                "business",
                "data",
            ],
            parallelizable=True,
            risk="high",
        ),
        constraints=(
            TaskConstraints()
        ),
        requested_mode="auto",
    )

    assert (
        plan.topology
        == "sequential"
    )

    assert (
        plan.max_parallelism
        == 1
    )


def test_explicit_parallel_overrides_risk():
    planner = (
        CollaborationPlanner()
    )

    plan = planner.plan(
        assignments=[
            assignment(
                1,
                "business",
            ),
            assignment(
                2,
                "data",
            ),
        ],
        profile=profile(
            capabilities=[
                "business",
                "data",
            ],
            parallelizable=False,
            risk="high",
        ),
        constraints=(
            TaskConstraints()
        ),
        requested_mode="parallel",
    )

    assert (
        plan.topology
        == "parallel"
    )