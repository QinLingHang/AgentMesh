from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.schemas import (
    AgentFeedback,
    ObservabilitySummary,
    RunScorecard,
    RuntimeCitation,
    TaskConstraints,
    TraceEvent,
)


def _clamp(value: float) -> float:
    return round(max(0.0, min(1.0, float(value))), 6)


def _detail(event: TraceEvent) -> dict[str, Any]:
    if not event.detail:
        return {}
    try:
        value = json.loads(event.detail)
    except (json.JSONDecodeError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _count_trace(trace: list[TraceEvent], *, kind: str, title: str | None = None, status: str | None = None) -> int:
    return sum(
        1
        for item in trace
        if item.kind == kind
        and (title is None or item.title == title)
        and (status is None or item.status == status)
    )


def _memory_selected(trace: list[TraceEvent]) -> int:
    for event in reversed(trace):
        if event.kind != "memory_retrieval":
            continue
        detail = _detail(event)
        try:
            return max(0, int(detail.get("selectedCount", 0) or 0))
        except (TypeError, ValueError):
            return 0
    return 0


def _rag_requested(trace: list[TraceEvent]) -> bool:
    for event in trace:
        if event.kind != "rag" or event.title != "RAG Route":
            continue
        return bool(_detail(event).get("retrieve", False))
    return False


def _failure_category(trace: list[TraceEvent]) -> str:
    errors = [item for item in trace if item.status == "error"]
    if not errors:
        return "none"
    priority = (
        ("approval", "approval"),
        ("tool", "tool"),
        ("mcp", "mcp"),
        ("model", "model"),
        ("rag", "rag"),
        ("memory", "memory"),
        ("agent", "agent"),
    )
    for family, category in priority:
        if any(
            item.kind == family or item.kind.startswith(f"{family}_")
            for item in errors
        ):
            return category
    return "runtime"


@dataclass(slots=True)
class ScorecardInputs:
    answer: str
    trace: list[TraceEvent]
    feedback: list[AgentFeedback]
    citations: list[RuntimeCitation]
    constraints: TaskConstraints
    elapsed_ms: int
    estimated_cost: float
    observability: ObservabilitySummary
    rag_grounding_sufficient: bool | None = None


def build_run_scorecard(inputs: ScorecardInputs) -> RunScorecard:
    """Build a deterministic, privacy-safe per-run scorecard.

    The per-run evaluator stays deterministic so production execution does not
    automatically introduce a second paid model call. V2's explicit ModelJudge
    uses a separate evaluation workflow and can be compared against this baseline.
    """

    trace = inputs.trace
    feedback = inputs.feedback
    observability = inputs.observability

    task_success = 1.0 if inputs.answer.strip() else 0.0
    if any(item.kind == "task" and item.title == "Task Completed" for item in trace):
        task_success = 1.0

    quality_scores = [
        float(item.quality_score)
        for item in feedback
        if item.quality_score is not None
    ]
    quality_evaluated = bool(quality_scores) or observability.quality_evaluations > 0
    answer_quality = (
        sum(quality_scores) / len(quality_scores)
        if quality_scores
        else observability.average_quality
    )
    # No quality evaluator ran (for example an approved Tool action or a
    # user-rejected action). Treat the dimension as neutral/not-applicable
    # instead of inventing a low score that would create a false policy alert.
    if not quality_evaluated:
        answer_quality = 1.0
    answer_quality = _clamp(answer_quality)

    rag_requested = _rag_requested(trace)
    if not rag_requested:
        groundedness = 1.0
        rag_quality = 1.0
        rag_mode = "not_required"
    else:
        if inputs.rag_grounding_sufficient is False:
            groundedness = 0.0
        elif inputs.citations:
            groundedness = 1.0
        else:
            groundedness = 0.25

        citation_scores = [max(0.0, min(1.0, float(item.score))) for item in inputs.citations]
        rag_quality = (
            sum(citation_scores) / len(citation_scores)
            if citation_scores
            else 0.0
        )
        rag_mode = "retrieved"

    if not rag_requested:
        citation_quality = 1.0
    elif not inputs.citations:
        citation_quality = 0.0
    else:
        citation_quality = _clamp(
            sum(max(0.0, min(1.0, float(item.score))) for item in inputs.citations)
            / len(inputs.citations)
        )

    correctness = answer_quality
    task_completion = task_success

    tool_started = _count_trace(trace, kind="tool", title="Tool Started")
    tool_completed = _count_trace(trace, kind="tool", title="Tool Completed")
    tool_failed = _count_trace(trace, kind="tool", status="error")
    mcp_started = _count_trace(trace, kind="mcp", title="MCP Call Started")
    mcp_completed = _count_trace(trace, kind="mcp", title="MCP Call Completed")
    mcp_failed = _count_trace(trace, kind="mcp", status="error")

    # MCP calls normally surface through the Tool wrapper too. Prefer Tool
    # lifecycle counts when present to avoid double-counting, but still score
    # a direct/isolated MCP lifecycle correctly when no Tool wrapper exists.
    if tool_started > 0:
        action_total = tool_started
        successful = min(tool_completed, action_total)
        failed_actions = tool_failed + mcp_failed
    else:
        action_total = mcp_started
        successful = min(mcp_completed, action_total)
        failed_actions = mcp_failed

    if action_total == 0:
        tool_reliability = 1.0 if failed_actions == 0 else 0.0
    else:
        tool_reliability = successful / action_total
        if failed_actions:
            tool_reliability = min(
                tool_reliability,
                max(0.0, 1.0 - failed_actions / max(action_total, 1)),
            )
    tool_reliability = _clamp(tool_reliability)

    selected_memory = _memory_selected(trace)
    memory_errors = _count_trace(trace, kind="memory_retrieval", status="error")
    if selected_memory == 0:
        memory_contribution = 1.0 if memory_errors == 0 else 0.5
        memory_mode = "not_used"
    else:
        memory_contribution = 1.0 if memory_errors == 0 else 0.5
        memory_mode = "used"

    latency_pass = inputs.elapsed_ms <= inputs.constraints.max_latency_ms
    cost_pass = inputs.estimated_cost <= inputs.constraints.max_cost
    quality_pass = (
        True
        if not quality_evaluated
        else answer_quality >= inputs.constraints.min_quality
    )
    budget_checks = {
        "latency": latency_pass,
        "cost": cost_pass,
        "quality": quality_pass,
    }
    budget_compliance = sum(1 for value in budget_checks.values() if value) / len(budget_checks)

    violations: list[str] = []
    if not latency_pass:
        violations.append("latency_budget_exceeded")
    if not cost_pass:
        violations.append("cost_budget_exceeded")
    if not quality_pass:
        violations.append("quality_below_minimum")

    overall = _clamp(
        0.20 * task_success
        + 0.20 * answer_quality
        + 0.10 * correctness
        + 0.15 * groundedness
        + 0.08 * citation_quality
        + 0.08 * tool_reliability
        + 0.07 * _clamp(rag_quality)
        + 0.04 * _clamp(memory_contribution)
        + 0.08 * _clamp(budget_compliance)
    )

    failure_category = _failure_category(trace)
    if task_success <= 0:
        status = "fail"
    elif violations or failure_category != "none":
        status = "warning"
    else:
        status = "pass"

    return RunScorecard(
        evaluator="p6_deterministic_v1",
        status=status,
        overallScore=overall,
        taskSuccess=_clamp(task_success),
        answerQuality=answer_quality,
        groundedness=_clamp(groundedness),
        correctness=_clamp(correctness),
        citationQuality=_clamp(citation_quality),
        taskCompletion=_clamp(task_completion),
        judgeReason="deterministic runtime scorecard",
        toolReliability=tool_reliability,
        ragQuality=_clamp(rag_quality),
        memoryContribution=_clamp(memory_contribution),
        budgetCompliance=_clamp(budget_compliance),
        latencyMs=max(0, int(inputs.elapsed_ms)),
        estimatedCost=round(max(0.0, float(inputs.estimated_cost)), 8),
        modelEstimatedCost=round(max(0.0, float(observability.model_estimated_cost)), 8),
        modelTokens=max(0, int(observability.model_total_tokens)),
        failureCategory=failure_category,
        violations=violations,
        signals={
            "ragMode": rag_mode,
            "memoryMode": memory_mode,
            "memorySelectedCount": selected_memory,
            "citationCount": len(inputs.citations),
            "toolStarted": tool_started,
            "toolCompleted": tool_completed,
            "toolErrors": tool_failed,
            "mcpStarted": mcp_started,
            "mcpCompleted": mcp_completed,
            "mcpErrors": mcp_failed,
            "latencyBudgetMs": inputs.constraints.max_latency_ms,
            "maxCost": inputs.constraints.max_cost,
            "minQuality": inputs.constraints.min_quality,
            "latencyBudgetPassed": latency_pass,
            "costBudgetPassed": cost_pass,
            "qualityBudgetPassed": quality_pass,
            "qualityEvaluated": quality_evaluated,
        },
    )
