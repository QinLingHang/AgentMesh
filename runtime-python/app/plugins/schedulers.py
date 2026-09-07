from abc import abstractmethod
from math import sqrt

from app.agents.capability import (
    effective_capability_profile,
)
from app.kernel import (
    AgentMeshPlugin,
    PluginKind,
    PluginManifest,
    RuntimeContext,
)
from app.schemas import (
    AgentProfile,
    Assignment,
    TaskConstraints,
    TaskProfile,
)


AVAILABLE_STATUSES = {
    "ACTIVE",
    "HEALTHY",
    "READY",
    "ONLINE",
}


def capability_match(
    agent: AgentProfile,
    capability: str,
) -> bool:
    caps = {
        item.lower()
        for item in agent.capabilities
    }

    normalized = (
        capability.strip().lower()
    )

    return (
        normalized in caps
        or "*" in caps
        or "general" in caps
    )


def is_agent_available(
    agent: AgentProfile,
) -> bool:
    status = (
        agent.status
        .strip()
        .upper()
    )

    return (
        status in AVAILABLE_STATUSES
        and agent.current_load < 1.0
    )


def constraint_fit(
    agent: AgentProfile,
    constraints: TaskConstraints,
    capability: str,
) -> bool:
    metrics = (
        effective_capability_profile(
            agent,
            capability,
        )
    )

    return (
        metrics.quality_score
        >= constraints.min_quality
        and metrics.avg_latency_ms
        <= constraints.max_latency_ms
        and metrics.avg_cost
        <= constraints.max_cost
    )


def score(
    agent: AgentProfile,
    constraints: TaskConstraints,
    capability: str | None = None,
) -> float:
    if capability:
        metrics = (
            effective_capability_profile(
                agent,
                capability,
            )
        )

        quality = min(
            max(
                metrics.quality_score,
                0.0,
            ),
            1.0,
        )

        reliability = min(
            max(
                metrics.success_rate,
                0.0,
            ),
            1.0,
        )

        latency = (
            metrics.avg_latency_ms
        )

        cost = (
            metrics.avg_cost
        )

    else:
        quality = min(
            max(
                agent.quality_score,
                0.0,
            ),
            1.0,
        )

        reliability = min(
            max(
                agent.success_rate,
                0.0,
            ),
            1.0,
        )

        latency = (
            agent.avg_latency_ms
        )

        cost = (
            agent.avg_cost
        )

    load = min(
        max(
            agent.current_load,
            0.0,
        ),
        1.0,
    )

    latency_ratio = min(
        latency
        / max(
            constraints.max_latency_ms,
            1,
        ),
        2.0,
    )

    cost_ratio = min(
        cost
        / max(
            constraints.max_cost,
            1e-6,
        ),
        2.0,
    )

    return (
        0.38 * quality
        + 0.30 * reliability
        - 0.12 * load
        - 0.10 * latency_ratio
        - 0.10 * cost_ratio
    )


def adaptive_score(
    agent: AgentProfile,
    constraints: TaskConstraints,
    capability: str,
) -> float:
    """
    Adaptive score =
        exploitation score
        +
        exploration bonus

    sample_count 越少，
    exploration bonus 越大。
    """

    metrics = (
        effective_capability_profile(
            agent,
            capability,
        )
    )

    exploitation = score(
        agent,
        constraints,
        capability,
    )

    exploration_bonus = (
        0.06
        / sqrt(
            metrics.sample_count + 1
        )
    )

    return (
        exploitation
        + exploration_bonus
    )


class SchedulerPlugin(
    AgentMeshPlugin
):
    async def setup(
        self,
        context: RuntimeContext,
    ) -> None:
        self.context = context

    @abstractmethod
    async def schedule(
        self,
        agents: list[AgentProfile],
        profile: TaskProfile,
        constraints: TaskConstraints,
    ) -> list[Assignment]:
        ...

    def candidates(
        self,
        agents: list[AgentProfile],
        capability: str,
    ) -> list[AgentProfile]:
        normalized = (
            capability.strip().lower()
        )

        exact = [
            agent
            for agent in agents
            if normalized
            in {
                item.lower()
                for item
                in agent.capabilities
            }
        ]

        if exact:
            return exact

        return [
            agent
            for agent in agents
            if capability_match(
                agent,
                capability,
            )
        ]


class FixedSchedulerPlugin(
    SchedulerPlugin
):
    manifest = PluginManifest(
        "scheduler.fixed",
        "Fixed Scheduler",
        "0.2.0",
        PluginKind.SCHEDULER,
    )

    async def schedule(
        self,
        agents,
        profile,
        constraints,
    ):
        if not agents:
            raise RuntimeError(
                "no available agents"
            )

        out = []

        for capability in (
            profile.required_capabilities
        ):
            candidates = self.candidates(
                agents,
                capability,
            )

            if not candidates:
                raise RuntimeError(
                    "capability not covered: "
                    f"{capability}"
                )

            selected = candidates[0]

            out.append(
                Assignment(
                    capability=capability,
                    agent_id=selected.id,
                    agent_name=selected.name,
                )
            )

        return out


class CapabilitySchedulerPlugin(
    SchedulerPlugin
):
    manifest = PluginManifest(
        "scheduler.capability",
        "Capability Scheduler",
        "0.2.0",
        PluginKind.SCHEDULER,
    )

    async def schedule(
        self,
        agents,
        profile,
        constraints,
    ):
        out = []

        for capability in (
            profile.required_capabilities
        ):
            candidates = self.candidates(
                agents,
                capability,
            )

            if not candidates:
                raise RuntimeError(
                    "capability not covered: "
                    f"{capability}"
                )

            selected = max(
                candidates,
                key=lambda agent: (
                    effective_capability_profile(
                        agent,
                        capability,
                    ).quality_score,

                    effective_capability_profile(
                        agent,
                        capability,
                    ).success_rate,
                ),
            )

            out.append(
                Assignment(
                    capability=capability,
                    agent_id=selected.id,
                    agent_name=selected.name,
                )
            )

        return out


class GreedySchedulerPlugin(
    SchedulerPlugin
):
    manifest = PluginManifest(
        "scheduler.greedy",
        "Greedy Multi-objective Scheduler",
        "0.2.0",
        PluginKind.SCHEDULER,
    )

    async def schedule(
        self,
        agents,
        profile,
        constraints,
    ):
        out = []
        used: set[int] = set()

        for capability in (
            profile.required_capabilities
        ):
            candidates = self.candidates(
                agents,
                capability,
            )

            if not candidates:
                raise RuntimeError(
                    "capability not covered: "
                    f"{capability}"
                )

            unused = [
                agent
                for agent in candidates
                if agent.id not in used
            ]

            selectable = (
                unused
                or candidates
            )

            selected = max(
                selectable,
                key=lambda agent: score(
                    agent,
                    constraints,
                    capability,
                ),
            )

            used.add(
                selected.id
            )

            out.append(
                Assignment(
                    capability=capability,
                    agent_id=selected.id,
                    agent_name=selected.name,
                )
            )

        return out


class AdaptiveSchedulerPlugin(
    SchedulerPlugin
):
    """P7 explainable adaptive Agent router.

    Historical capability metrics come from the Go/MySQL control plane.  The
    router combines quality, reliability, latency, cost, load and bounded
    exploration using task-aware objective weights.  ``last_routing_decisions``
    is developer-facing observability consumed by Runtime Trace.
    """

    manifest = PluginManifest(
        "scheduler.adaptive",
        "Adaptive Collaboration Scheduler",
        "0.2.0",
        PluginKind.SCHEDULER,
    )

    def __init__(self) -> None:
        self.last_routing_decisions: list[dict] = []

    async def schedule(
        self,
        agents: list[AgentProfile],
        profile: TaskProfile,
        constraints: TaskConstraints,
    ) -> list[Assignment]:
        # Local import avoids a module cycle: the router intentionally reuses
        # the public scheduler capability/availability helpers above.
        from app.optimization.agent_router import AdaptiveAgentRouter

        router = AdaptiveAgentRouter()
        assignments: list[Assignment] = []
        used: set[int] = set()
        decisions: list[dict] = []

        for capability in profile.required_capabilities:
            decision = router.route(
                agents=agents,
                capability=capability,
                profile=profile,
                constraints=constraints,
                used_agent_ids=used,
            )
            used.add(decision.selected_agent_id)
            decisions.append(decision.as_dict())
            assignments.append(
                Assignment(
                    capability=capability,
                    agent_id=decision.selected_agent_id,
                    agent_name=decision.selected_agent_name,
                )
            )

        self.last_routing_decisions = decisions
        return assignments
