from __future__ import annotations

from math import sqrt

from app.agents.capability import effective_capability_profile
from app.optimization.contracts import AgentCandidateScore, AgentRouteDecision
from app.optimization.policy import objective_weights
from app.plugins.schedulers import capability_match, is_agent_available
from app.schemas import AgentProfile, TaskConstraints, TaskProfile


def _positive_budget_score(value: float, limit: float) -> float:
    if limit <= 0:
        return 1.0
    ratio = max(0.0, value) / max(limit, 1e-9)
    return max(0.0, 1.0 - min(ratio, 2.0) / 2.0)


class AdaptiveAgentRouter:
    """Explainable multi-objective Agent router.

    Historical capability profiles are supplied by Go/MySQL and therefore
    survive Python Runtime restarts. The router combines those learned metrics
    with request constraints and a bounded cold-start exploration bonus.
    """

    def route(
        self,
        *,
        agents: list[AgentProfile],
        capability: str,
        profile: TaskProfile,
        constraints: TaskConstraints,
        used_agent_ids: set[int] | None = None,
    ) -> AgentRouteDecision:
        used_agent_ids = used_agent_ids or set()
        normalized = capability.strip().lower()
        exact = [
            agent
            for agent in agents
            if normalized in {item.strip().lower() for item in agent.capabilities}
        ]
        candidates = exact or [
            agent for agent in agents if capability_match(agent, capability)
        ]
        candidates = [agent for agent in candidates if is_agent_available(agent)]
        if not candidates:
            raise RuntimeError(f"no available agent for capability: {capability}")

        unused = [agent for agent in candidates if agent.id not in used_agent_ids]
        selectable = unused or candidates
        weights = objective_weights(profile)
        scored: list[AgentCandidateScore] = []

        for agent in selectable:
            metrics = effective_capability_profile(agent, capability)
            quality = min(max(float(metrics.quality_score), 0.0), 1.0)
            reliability = min(max(float(metrics.success_rate), 0.0), 1.0)
            load = min(max(float(agent.current_load), 0.0), 1.0)
            latency_score = _positive_budget_score(
                float(metrics.avg_latency_ms), float(constraints.max_latency_ms)
            )
            cost_score = _positive_budget_score(
                float(metrics.avg_cost), float(constraints.max_cost)
            )
            exploration = 1.0 / sqrt(max(0, metrics.sample_count) + 1.0)

            violations: list[str] = []
            if quality < constraints.min_quality:
                violations.append("quality")
            if metrics.avg_latency_ms > constraints.max_latency_ms:
                violations.append("latency")
            if constraints.max_cost > 0 and metrics.avg_cost > constraints.max_cost:
                violations.append("cost")

            score = (
                weights.quality * quality
                + weights.reliability * reliability
                + weights.latency * latency_score
                + weights.cost * cost_score
                + weights.load * (1.0 - load)
                + weights.exploration * exploration
            )
            if exact and agent in exact:
                score += 0.015
            if violations:
                score -= 0.08 * len(violations)

            reasons: list[str] = []
            if quality >= max(constraints.min_quality, 0.85):
                reasons.append("strong_quality")
            if reliability >= 0.9:
                reasons.append("strong_reliability")
            if metrics.sample_count < 3:
                reasons.append("cold_start_exploration")
            if not violations:
                reasons.append("within_constraints")
            if load >= 0.75:
                reasons.append("high_current_load")

            scored.append(
                AgentCandidateScore(
                    agent_id=agent.id,
                    agent_name=agent.name,
                    capability=capability,
                    score=score,
                    feasible=not violations,
                    quality=quality,
                    reliability=reliability,
                    latency_ms=metrics.avg_latency_ms,
                    avg_cost=metrics.avg_cost,
                    load=load,
                    sample_count=metrics.sample_count,
                    exploration_bonus=weights.exploration * exploration,
                    constraint_violations=violations,
                    reasons=reasons,
                )
            )

        feasible = [item for item in scored if item.feasible]
        pool = feasible or scored
        selected = max(
            pool,
            key=lambda item: (item.score, -item.agent_id),
        )
        degraded = not bool(feasible)
        reason = (
            "best feasible multi-objective candidate"
            if not degraded
            else "no candidate satisfied all constraints; selected best-effort candidate"
        )
        ordered = sorted(scored, key=lambda item: (-item.score, item.agent_id))
        return AgentRouteDecision(
            capability=capability,
            selected_agent_id=selected.agent_id,
            selected_agent_name=selected.agent_name,
            selected_score=selected.score,
            degraded=degraded,
            weights=weights,
            reason=reason,
            candidates=ordered,
        )
