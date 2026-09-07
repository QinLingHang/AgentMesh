from __future__ import annotations

from dataclasses import dataclass, field

from app.optimization import AdaptiveAgentRouter
from app.plugins.schedulers import adaptive_score, capability_match, constraint_fit, is_agent_available
from app.schemas import AgentProfile, TaskConstraints, TaskProfile


@dataclass(slots=True)
class ReplacementDecision:
    agent: AgentProfile
    score: float
    constraint_fit: bool
    reason: str = ""
    candidates: list[dict] = field(default_factory=list)


class RuntimeRescheduler:
    def choose_replacement(
        self,
        *,
        agents: list[AgentProfile],
        capability: str,
        constraints: TaskConstraints,
        attempted_agent_ids: set[int],
        profile: TaskProfile | None = None,
    ) -> ReplacementDecision | None:
        candidates = [
            agent
            for agent in agents
            if (
                agent.id not in attempted_agent_ids
                and capability_match(agent, capability)
                and is_agent_available(agent)
            )
        ]
        if not candidates:
            return None

        if profile is not None:
            decision = AdaptiveAgentRouter().route(
                agents=candidates,
                capability=capability,
                profile=profile,
                constraints=constraints,
            )
            selected = next(item for item in candidates if item.id == decision.selected_agent_id)
            return ReplacementDecision(
                agent=selected,
                score=decision.selected_score,
                constraint_fit=not decision.degraded,
                reason=decision.reason,
                candidates=[item.as_dict() for item in decision.candidates],
            )

        feasible = [
            agent
            for agent in candidates
            if constraint_fit(agent, constraints, capability)
        ]
        pool = feasible or candidates
        selected = max(pool, key=lambda agent: adaptive_score(agent, constraints, capability))
        return ReplacementDecision(
            agent=selected,
            score=adaptive_score(selected, constraints, capability),
            constraint_fit=constraint_fit(selected, constraints, capability),
            reason="legacy adaptive replacement",
        )
