from __future__ import annotations

from dataclasses import dataclass

from app.optimization.agent_router import AdaptiveAgentRouter
from app.plugins.schedulers import score
from app.schemas import AgentProfile, TaskConstraints, TaskProfile


@dataclass(slots=True)
class RoutingPolicyComparison:
    capability: str
    greedy_agent: str
    adaptive_agent: str
    adaptive_score: float
    degraded: bool


def compare_agent_routing_policies(
    *,
    agents: list[AgentProfile],
    profile: TaskProfile,
    constraints: TaskConstraints,
) -> list[RoutingPolicyComparison]:
    router = AdaptiveAgentRouter()
    out: list[RoutingPolicyComparison] = []
    for capability in profile.required_capabilities:
        candidates = [
            agent for agent in agents
            if capability.strip().lower() in {item.strip().lower() for item in agent.capabilities}
            or "general" in {item.strip().lower() for item in agent.capabilities}
            or "*" in {item.strip().lower() for item in agent.capabilities}
        ]
        if not candidates:
            continue
        greedy = max(candidates, key=lambda item: score(item, constraints, capability))
        adaptive = router.route(
            agents=agents,
            capability=capability,
            profile=profile,
            constraints=constraints,
        )
        out.append(
            RoutingPolicyComparison(
                capability=capability,
                greedy_agent=greedy.name,
                adaptive_agent=adaptive.selected_agent_name,
                adaptive_score=round(adaptive.selected_score, 6),
                degraded=adaptive.degraded,
            )
        )
    return out
