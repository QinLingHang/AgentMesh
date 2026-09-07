from __future__ import annotations

import json

from app.schemas import AgentFeedback, DynamicDAG, ObservabilitySummary, TraceEvent


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
    model_provider = ""
    model_name = ""

    tool_calls = 0
    tool_successes = 0
    tool_failures = 0
    mcp_events = 0
    reschedules = 0

    retrieval_mode = ""
    rag_latency_ms = 0
    rag_started_elapsed: int | None = None
    rag_raw_hits = 0
    rag_hits = 0
    rag_context_hits = 0
    rag_text_candidates = 0
    rag_visual_candidates = 0

    for item in trace:
        if item.kind == "model" and item.title == "Model Call Completed":
            model_calls += 1
            detail = _parse_detail(item.detail)
            model_input_tokens += _int(detail.get("input_tokens"))
            model_output_tokens += _int(detail.get("output_tokens"))
            model_total_tokens += _int(detail.get("total_tokens"))
            model_latency_ms += _int(detail.get("latency_ms"))
            model_estimated_cost += _float(detail.get("estimated_cost"))
            saw_model_cost = True
            if not bool(detail.get("cost_known", False)):
                model_cost_known = False
            provider = str(detail.get("provider") or "").strip()
            model = str(detail.get("model") or "").strip()
            if provider:
                model_provider = provider
            if model:
                model_name = model

        elif item.kind == "tool" and item.title == "Tool Started":
            tool_calls += 1
        elif item.kind == "tool" and item.title == "Tool Completed" and item.status == "completed":
            tool_successes += 1
        elif item.kind == "tool" and item.status == "error":
            tool_failures += 1
        elif item.kind == "mcp":
            mcp_events += 1
        elif item.kind == "reschedule" and item.status == "completed":
            reschedules += 1

        if item.kind == "rag" and item.title == "RAG Route":
            detail = _parse_detail(item.detail)
            retrieval_mode = str(detail.get("retrievalMode") or retrieval_mode)
        elif item.kind == "rag" and item.title == "RAG Retrieval Started":
            rag_started_elapsed = max(0, int(item.elapsed_ms))
            detail = _parse_detail(item.detail)
            retrieval_mode = str(detail.get("retrievalMode") or retrieval_mode)
        elif item.kind == "rag" and item.title == "RAG Retrieval Completed":
            detail = _parse_detail(item.detail)
            retrieval_mode = str(detail.get("retrievalMode") or retrieval_mode)
            rag_raw_hits = _int(detail.get("rawHits"))
            rag_hits = _int(detail.get("hits"))
            rag_context_hits = _int(detail.get("contextHits"))
            rag_text_candidates = _int(detail.get("textCandidates"))
            rag_visual_candidates = _int(detail.get("visualCandidates"))
            if rag_started_elapsed is not None:
                rag_latency_ms = max(0, int(item.elapsed_ms) - rag_started_elapsed)

    agent_attempts = len(feedback)
    agent_successes = sum(1 for item in feedback if item.success)
    agent_failures = agent_attempts - agent_successes
    quality_scores = [item.quality_score for item in feedback if item.quality_score is not None]
    average_quality = sum(quality_scores) / len(quality_scores) if quality_scores else 0.0
    dag_completed_nodes = sum(1 for node in dag.nodes if node.status == "completed")
    dag_skipped_nodes = sum(1 for node in dag.nodes if node.status == "skipped")

    return ObservabilitySummary(
        modelCalls=model_calls,
        modelInputTokens=model_input_tokens,
        modelOutputTokens=model_output_tokens,
        modelTotalTokens=model_total_tokens,
        modelLatencyMs=model_latency_ms,
        toolCalls=tool_calls,
        mcpEvents=mcp_events,
        agentAttempts=agent_attempts,
        agentSuccesses=agent_successes,
        agentFailures=agent_failures,
        reschedules=reschedules,
        dagCompletedNodes=dag_completed_nodes,
        dagSkippedNodes=dag_skipped_nodes,
        qualityEvaluations=len(quality_scores),
        averageQuality=round(average_quality, 6),
        modelEstimatedCost=round(model_estimated_cost, 8),
        modelCostKnown=saw_model_cost and model_cost_known,
        modelProvider=model_provider,
        modelName=model_name,
        retrievalMode=retrieval_mode,
        ragLatencyMs=rag_latency_ms,
        ragRawHits=rag_raw_hits,
        ragHits=rag_hits,
        ragContextHits=rag_context_hits,
        ragTextCandidates=rag_text_candidates,
        ragVisualCandidates=rag_visual_candidates,
        toolSuccesses=tool_successes,
        toolFailures=tool_failures,
    )


def _parse_detail(detail: str) -> dict:
    if not detail:
        return {}
    try:
        value = json.loads(detail)
        return value if isinstance(value, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _int(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _float(value: object) -> float:
    try:
        return max(0.0, float(value or 0.0))
    except (TypeError, ValueError):
        return 0.0
