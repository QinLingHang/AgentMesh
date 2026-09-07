from __future__ import annotations

import json

from app.schemas import (
    AgentFeedback,
    DynamicDAG,
    ObservabilitySummary,
    TraceEvent,
)


def build_observability_summary(
    *,
    trace: list[TraceEvent],
    feedback: list[AgentFeedback],
    dag: DynamicDAG,
) -> ObservabilitySummary:
    model_calls = 0

    model_input_tokens = 0
    model_output_tokens = 0
    model_total_tokens = 0
    model_latency_ms = 0
    model_estimated_cost = 0.0
    saw_model_cost = False
    model_cost_known = True

    tool_calls = 0
    tool_successes = 0
    tool_failures = 0
    mcp_events = 0
    reschedules = 0

    for item in trace:
        if item.kind == "model":
            if (
                item.title
                == "Model Call Completed"
            ):
                model_calls += 1

                detail = (
                    _parse_detail(
                        item.detail
                    )
                )

                model_input_tokens += int(
                    detail.get(
                        "input_tokens",
                        0,
                    )
                    or 0
                )

                model_output_tokens += int(
                    detail.get(
                        "output_tokens",
                        0,
                    )
                    or 0
                )

                model_total_tokens += int(
                    detail.get(
                        "total_tokens",
                        0,
                    )
                    or 0
                )

                model_latency_ms += int(
                    detail.get(
                        "latency_ms",
                        0,
                    )
                    or 0
                )

                model_estimated_cost += float(
                    detail.get(
                        "estimated_cost",
                        0.0,
                    )
                    or 0.0
                )
                saw_model_cost = True
                if not bool(detail.get("cost_known", False)):
                    model_cost_known = False

        elif (
            item.kind == "tool"
            and item.title
            == "Tool Started"
        ):
            tool_calls += 1

        elif (
            item.kind == "tool"
            and item.title
            == "Tool Completed"
            and item.status == "completed"
        ):
            tool_successes += 1

        elif (
            item.kind == "tool"
            and item.status == "error"
        ):
            tool_failures += 1

        elif item.kind == "mcp":
            mcp_events += 1

        elif (
            item.kind
            == "reschedule"
            and item.status
            == "completed"
        ):
            reschedules += 1

    agent_attempts = len(
        feedback
    )

    agent_successes = sum(
        1
        for item in feedback
        if item.success
    )

    agent_failures = (
        agent_attempts
        - agent_successes
    )

    quality_scores = [
        item.quality_score
        for item in feedback
        if item.quality_score
        is not None
    ]

    average_quality = (
        sum(
            quality_scores
        )
        / len(
            quality_scores
        )
        if quality_scores
        else 0.0
    )

    dag_completed_nodes = sum(
        1
        for node in dag.nodes
        if node.status
        == "completed"
    )

    dag_skipped_nodes = sum(
        1
        for node in dag.nodes
        if node.status
        == "skipped"
    )

    return ObservabilitySummary(
        modelCalls=(
            model_calls
        ),
        modelInputTokens=(
            model_input_tokens
        ),
        modelOutputTokens=(
            model_output_tokens
        ),
        modelTotalTokens=(
            model_total_tokens
        ),
        modelLatencyMs=(
            model_latency_ms
        ),
        toolCalls=(
            tool_calls
        ),
        mcpEvents=(
            mcp_events
        ),
        agentAttempts=(
            agent_attempts
        ),
        agentSuccesses=(
            agent_successes
        ),
        agentFailures=(
            agent_failures
        ),
        reschedules=(
            reschedules
        ),
        dagCompletedNodes=(
            dag_completed_nodes
        ),
        dagSkippedNodes=(
            dag_skipped_nodes
        ),
        qualityEvaluations=(
            len(
                quality_scores
            )
        ),
        averageQuality=round(
            average_quality,
            6,
        ),
        modelEstimatedCost=round(
            model_estimated_cost,
            8,
        ),
        modelCostKnown=(
            saw_model_cost
            and model_cost_known
        ),
        toolSuccesses=tool_successes,
        toolFailures=tool_failures,
    )


def _parse_detail(
    detail: str,
) -> dict:
    if not detail:
        return {}

    try:
        value = json.loads(
            detail
        )

        if isinstance(
            value,
            dict,
        ):
            return value

    except (
        json.JSONDecodeError,
        TypeError,
    ):
        pass

    return {}