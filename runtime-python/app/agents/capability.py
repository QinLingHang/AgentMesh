from __future__ import annotations

from app.schemas import (
    AgentCapabilityProfile,
    AgentFeedback,
    AgentProfile,
)


DEFAULT_FEEDBACK_ALPHA = 0.2


def find_capability_profile(
    agent: AgentProfile,
    capability: str,
) -> AgentCapabilityProfile | None:
    normalized = capability.strip().lower()

    for profile in agent.capability_profiles:
        if (
            profile.capability
            .strip()
            .lower()
            == normalized
        ):
            return profile

    return None


def effective_capability_profile(
    agent: AgentProfile,
    capability: str,
) -> AgentCapabilityProfile:
    existing = find_capability_profile(
        agent,
        capability,
    )

    if existing is not None:
        return existing

    return AgentCapabilityProfile(
        capability=capability,
        qualityScore=agent.quality_score,
        avgLatencyMs=agent.avg_latency_ms,
        avgCost=agent.avg_cost,
        successRate=agent.success_rate,
        failureRate=agent.failure_rate,
        sampleCount=0,
    )


def apply_capability_feedback(
    agent: AgentProfile,
    feedback: AgentFeedback,
    *,
    alpha: float = DEFAULT_FEEDBACK_ALPHA,
) -> AgentCapabilityProfile:
    alpha = min(
        max(alpha, 0.0),
        1.0,
    )

    profile = find_capability_profile(
        agent,
        feedback.capability,
    )

    if profile is None:
        profile = effective_capability_profile(
            agent,
            feedback.capability,
        )

        agent.capability_profiles.append(
            profile
        )

    success_value = (
        1.0
        if feedback.success
        else 0.0
    )

    profile.success_rate = round(
        (
            (1.0 - alpha)
            * profile.success_rate
        )
        + (
            alpha
            * success_value
        ),
        6,
    )

    profile.failure_rate = round(
        1.0 - profile.success_rate,
        6,
    )

    profile.avg_latency_ms = max(
        1,
        int(
            round(
                (
                    (1.0 - alpha)
                    * profile.avg_latency_ms
                )
                + (
                    alpha
                    * feedback.latency_ms
                )
            )
        ),
    )

    profile.avg_cost = round(
        (
            (1.0 - alpha)
            * profile.avg_cost
        )
        + (
            alpha
            * feedback.cost
        ),
        6,
    )


    if feedback.quality_score is not None:
        profile.quality_score = round(
            (
                (1.0 - alpha)
                * profile.quality_score
            )
            + (
                alpha
                * feedback.quality_score
            ),
            6,
        )

    profile.sample_count += 1

    return profile