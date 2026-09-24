import pytest
from app.eval.baseline import compare_scorecards
from app.eval.scorecard import ScorecardInputs, build_run_scorecard
from app.schemas import (
    AgentFeedback,
    DynamicDAG,
    ObservabilitySummary,
    RuntimeCitation,
    TaskConstraints,
    TraceEvent,
)
from app.services.observability import build_observability_summary


def _trace(kind: str, title: str, status: str = "completed", detail: str = "") -> TraceEvent:
    return TraceEvent(kind=kind, title=title, status=status, detail=detail)


def test_scorecard_passes_clean_grounded_run():
    trace = [
        _trace("rag", "RAG Route", detail='{"retrieve": true}'),
        _trace("tool", "Tool Started", "running"),
        _trace("tool", "Tool Completed"),
        _trace("task", "Task Completed"),
    ]
    feedback = [
        AgentFeedback(
            agentId=1,
            capability="general",
            success=True,
            latencyMs=100,
            cost=.01,
            qualityScore=.92,
        )
    ]
    obs = ObservabilitySummary(
        modelCalls=1,
        modelTotalTokens=100,
        averageQuality=.92,
        qualityEvaluations=1,
    )
    card = build_run_scorecard(
        ScorecardInputs(
            answer="Grounded answer [1]",
            trace=trace,
            feedback=feedback,
            citations=[
                RuntimeCitation(
                    citationId=1,
                    label="[1]",
                    documentId="d1",
                    source="doc",
                    score=.9,
                )
            ],
            constraints=TaskConstraints(
                maxLatencyMs=1000,
                maxCost=.1,
                minQuality=.8,
            ),
            elapsed_ms=200,
            estimated_cost=.01,
            observability=obs,
            rag_grounding_sufficient=True,
        )
    )
    assert card.status == "pass"
    assert card.overall_score >= .8
    assert card.groundedness == 1
    assert card.tool_reliability == 1
    assert card.violations == []


def test_scorecard_warns_on_budget_violation_without_leaking_content():
    card = build_run_scorecard(
        ScorecardInputs(
            answer="answer",
            trace=[_trace("task", "Task Completed")],
            feedback=[
                AgentFeedback(
                    agentId=1,
                    capability="general",
                    success=True,
                    latencyMs=100,
                    cost=.2,
                    qualityScore=.5,
                )
            ],
            citations=[],
            constraints=TaskConstraints(
                maxLatencyMs=10,
                maxCost=.1,
                minQuality=.8,
            ),
            elapsed_ms=100,
            estimated_cost=.2,
            observability=ObservabilitySummary(
                averageQuality=.5,
                qualityEvaluations=1,
            ),
        )
    )
    assert card.status == "warning"
    assert set(card.violations) == {
        "latency_budget_exceeded",
        "cost_budget_exceeded",
        "quality_below_minimum",
    }
    payload = card.model_dump(by_alias=True)
    dumped = card.model_dump_json()
    # Scorecard may legitimately expose the metric name `answerQuality`, but
    # must never carry the raw answer or generic raw-content fields.
    assert "answer" not in payload
    assert "content" not in payload
    assert "rawAnswer" not in payload
    assert '"answer":' not in dumped
    assert '"content":' not in dumped


def test_observability_counts_model_cost_and_tool_outcomes():
    summary = build_observability_summary(
        trace=[
            _trace(
                "model",
                "Model Call Completed",
                detail='{"estimated_cost":0.012,"cost_known":true,"total_tokens":50}',
            ),
            _trace("tool", "Tool Started", "running"),
            _trace("tool", "Tool Completed"),
            _trace("tool", "Tool Started", "running"),
            _trace("tool", "Tool Failed", "error"),
        ],
        feedback=[],
        dag=DynamicDAG(nodes=[], edges=[]),
    )
    assert summary.model_estimated_cost == .012
    assert summary.model_cost_known is True
    assert summary.tool_calls == 2
    assert summary.tool_successes == 1
    assert summary.tool_failures == 1


def test_baseline_comparison_flags_regression():
    low = build_run_scorecard(
        ScorecardInputs(
            answer="x",
            trace=[_trace("task", "Task Completed")],
            feedback=[
                AgentFeedback(
                    agentId=1,
                    capability="general",
                    success=True,
                    latencyMs=50,
                    cost=.2,
                    qualityScore=.2,
                )
            ],
            citations=[],
            constraints=TaskConstraints(
                maxLatencyMs=10,
                maxCost=.1,
                minQuality=.8,
            ),
            elapsed_ms=100,
            estimated_cost=.2,
            observability=ObservabilitySummary(
                averageQuality=.2,
                qualityEvaluations=1,
            ),
        )
    )
    result = compare_scorecards(
        [low],
        baseline_mean=.95,
        regression_tolerance=.01,
    )
    assert result.regressed is True


def test_scorecard_handles_rag_memory_and_failure_taxonomy_without_raw_payloads():
    card = build_run_scorecard(
        ScorecardInputs(
            answer="safe final",
            trace=[
                _trace("rag", "RAG Route", detail='{"retrieve": true}'),
                _trace(
                    "memory_retrieval",
                    "Memory Retrieval",
                    detail='{"selectedCount": 2, "content": "must-not-propagate"}',
                ),
                _trace("mcp", "MCP Call Started", "running"),
                _trace("mcp", "MCP Call Failed", "error", "credential=must-not-propagate"),
                _trace("task", "Task Completed"),
            ],
            feedback=[],
            citations=[],
            constraints=TaskConstraints(maxLatencyMs=1000, maxCost=1, minQuality=.8),
            elapsed_ms=20,
            estimated_cost=0,
            observability=ObservabilitySummary(),
            rag_grounding_sufficient=False,
        )
    )
    assert card.groundedness == 0
    assert card.rag_quality == 0
    assert card.memory_contribution == 1
    assert card.tool_reliability == 0
    assert card.failure_category == "mcp"
    dumped = card.model_dump_json()
    assert "must-not-propagate" not in dumped
    assert "credential=" not in dumped


def test_baseline_comparison_tolerates_small_noise():
    healthy = build_run_scorecard(
        ScorecardInputs(
            answer="ok",
            trace=[_trace("task", "Task Completed")],
            feedback=[],
            citations=[],
            constraints=TaskConstraints(maxLatencyMs=1000, maxCost=1, minQuality=.8),
            elapsed_ms=1,
            estimated_cost=0,
            observability=ObservabilitySummary(),
        )
    )
    result = compare_scorecards([healthy], baseline_mean=.99, regression_tolerance=.02)
    assert result.regressed is False


def test_memory_retrieval_failure_is_degraded_but_never_copies_detail():
    card = build_run_scorecard(
        ScorecardInputs(
            answer="safe",
            trace=[
                _trace(
                    "memory_retrieval",
                    "Memory Retrieval",
                    "error",
                    "password=never-copy-this",
                ),
                _trace("task", "Task Completed"),
            ],
            feedback=[],
            citations=[],
            constraints=TaskConstraints(maxLatencyMs=1000, maxCost=1, minQuality=.8),
            elapsed_ms=10,
            estimated_cost=0,
            observability=ObservabilitySummary(),
        )
    )
    assert card.memory_contribution == .5
    assert card.failure_category == "memory"
    assert "never-copy-this" not in card.model_dump_json()


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("approval", "approval"),
        ("tool", "tool"),
        ("mcp", "mcp"),
        ("model", "model"),
        ("rag", "rag"),
        ("memory", "memory"),
        ("agent", "agent"),
        ("other", "runtime"),
    ],
)
def test_failure_taxonomy_is_metadata_only(kind, expected):
    card = build_run_scorecard(
        ScorecardInputs(
            answer="safe",
            trace=[
                _trace(kind, "Fixture Failed", "error", "token=top-secret"),
                _trace("task", "Task Completed"),
            ],
            feedback=[],
            citations=[],
            constraints=TaskConstraints(maxLatencyMs=1000, maxCost=1, minQuality=.8),
            elapsed_ms=10,
            estimated_cost=0,
            observability=ObservabilitySummary(),
        )
    )
    assert card.failure_category == expected
    assert "top-secret" not in card.model_dump_json()


def test_evaluation_baseline_jsonl_is_valid_and_has_required_cases():
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "evals" / "evaluation_baseline_cases.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert rows
    ids = {row["id"] for row in rows}
    assert {"general-answer", "tool-calculator", "memory-recall", "project-rag"} <= ids
    for row in rows:
        assert isinstance(row.get("task"), str) and row["task"].strip()
        assert isinstance(row.get("expected"), dict)
