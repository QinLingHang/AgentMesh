from app.schemas import (
    AgentFeedback,
    DAGNode,
    DynamicDAG,
    TraceEvent,
)
from app.services.observability import (
    build_observability_summary,
)


def test_observability_summary():
    trace = [
        TraceEvent(
            kind="model",
            title=(
                "Model Call Completed"
            ),
            status="completed",
            detail=(
                '{"latency_ms": 120, '
                '"input_tokens": 10, '
                '"output_tokens": 20, '
                '"total_tokens": 30}'
            ),
        ),
        TraceEvent(
            kind="tool",
            title="Tool Started",
            status="running",
        ),
        TraceEvent(
            kind="reschedule",
            title=(
                "Runtime Rescheduler"
            ),
            status="completed",
        ),
        TraceEvent(
            kind="mcp",
            title="MCP Tool Discovered",
            status="completed",
        ),
    ]

    feedback = [
        AgentFeedback(
            agentId=1,
            capability="business",
            success=True,
            latencyMs=100,
            cost=0.01,
            qualityScore=0.9,
        ),
        AgentFeedback(
            agentId=2,
            capability="business",
            success=False,
            latencyMs=200,
            cost=0.01,
            errorType="TimeoutError",
        ),
    ]

    dag = DynamicDAG(
        nodes=[
            DAGNode(
                id="task",
                label="Task",
                kind="task",
                status="completed",
            ),
            DAGNode(
                id="agent-1",
                label="Agent",
                kind="agent",
                status="completed",
            ),
            DAGNode(
                id="agent-2",
                label="Optional",
                kind="agent",
                status="skipped",
            ),
        ],
        edges=[],
    )

    summary = (
        build_observability_summary(
            trace=trace,
            feedback=feedback,
            dag=dag,
        )
    )

    assert (
        summary.model_calls
        == 1
    )

    assert (
        summary.model_input_tokens
        == 10
    )

    assert (
        summary.model_output_tokens
        == 20
    )

    assert (
        summary.model_total_tokens
        == 30
    )

    assert (
        summary.model_latency_ms
        == 120
    )

    assert (
        summary.tool_calls
        == 1
    )

    assert (
        summary.mcp_events
        == 1
    )

    assert (
        summary.reschedules
        == 1
    )

    assert (
        summary.agent_attempts
        == 2
    )

    assert (
        summary.agent_successes
        == 1
    )

    assert (
        summary.agent_failures
        == 1
    )

    assert (
        summary.quality_evaluations
        == 1
    )

    assert (
        summary.average_quality
        == 0.9
    )

    assert (
        summary.dag_completed_nodes
        == 2
    )

    assert (
        summary.dag_skipped_nodes
        == 1
    )
def test_trace_event_accepts_skipped_status():
    event = TraceEvent(
        kind="mcp",
        title="MCP Discovery Backoff",
        status="skipped",
        detail="discovery suppressed by backoff",
    )

    assert (
        event.status
        == "skipped"
    )