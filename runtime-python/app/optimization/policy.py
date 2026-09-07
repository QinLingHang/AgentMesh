from __future__ import annotations

from app.optimization.contracts import ObjectiveWeights
from app.schemas import TaskProfile


def objective_weights(profile: TaskProfile) -> ObjectiveWeights:
    """Task-aware multi-objective weights used by Agent and Model routing.

    The weights are deterministic and deliberately simple enough to explain in
    Run Details. High-risk/high-complexity work favours quality/reliability;
    low-complexity work gives latency/cost more influence.
    """

    if profile.risk_level == "high" or profile.complexity == "high":
        return ObjectiveWeights(
            quality=0.38,
            reliability=0.30,
            latency=0.09,
            cost=0.07,
            load=0.05,
            exploration=0.11,
        )

    if profile.complexity == "low" and profile.risk_level == "low":
        return ObjectiveWeights(
            quality=0.27,
            reliability=0.23,
            latency=0.17,
            cost=0.14,
            load=0.08,
            exploration=0.11,
        )

    return ObjectiveWeights(
        quality=0.33,
        reliability=0.27,
        latency=0.12,
        cost=0.10,
        load=0.07,
        exploration=0.11,
    )
