import asyncio
import json

import pytest

from app.schemas import AgentProfile, RuntimeRequest, TaskConstraints
from app.services import RuntimeEngine, create_registry
from app.services.dag_executor import DAGExecutionError
import app.services.engine as engine_module


def run(coro):
    return asyncio.run(coro)


def _agent(*, agent_id: int = 1, name: str = "General", endpoint: str = "internal://general", cost: float = 0.01) -> AgentProfile:
    return AgentProfile(
        id=agent_id,
        name=name,
        endpoint=endpoint,
        protocol="internal",
        capabilities=["general"],
        avgCost=cost,
        avgLatencyMs=50,
        qualityScore=.9,
        successRate=.99,
    )


def test_runtime_completed_task_returns_scorecard_and_privacy_safe_eval_trace(monkeypatch):
    monkeypatch.setattr(engine_module.settings, "eval_scorecard_enabled", True)

    async def scenario():
        registry = await create_registry()
        try:
            return await RuntimeEngine(registry).run(
                RuntimeRequest(
                    user_id=1,
                    request_id="evaluation-runtime-scorecard",
                    task="Explain AgentMesh briefly",
                    agents=[_agent()],
                    constraints=TaskConstraints(maxLatencyMs=5000, maxCost=.2, minQuality=.5),
                )
            )
        finally:
            await registry.stop_all()

    result = run(scenario())
    assert result.status == "COMPLETED"
    assert result.scorecard is not None
    assert 0 <= result.scorecard.overall_score <= 1
    assert result.scorecard.task_success == 1
    assert result.scorecard.failure_category == "none"

    events = [event for event in result.trace if event.kind == "eval" and event.title == "Run Scorecard"]
    assert len(events) == 1
    assert events[0].status == "completed"
    detail = json.loads(events[0].detail)
    assert "answer" not in detail
    assert "content" not in detail
    assert "rawAnswer" not in detail


def test_runtime_eval_builder_failure_isolated_from_successful_task(monkeypatch):
    monkeypatch.setattr(engine_module.settings, "eval_scorecard_enabled", True)

    def explode(_inputs):
        raise RuntimeError("fixture-scorecard-failure-secret")

    monkeypatch.setattr(engine_module, "build_run_scorecard", explode)

    async def scenario():
        registry = await create_registry()
        try:
            return await RuntimeEngine(registry).run(
                RuntimeRequest(
                    user_id=1,
                    request_id="evaluation-isolation",
                    task="hello",
                    agents=[_agent()],
                    constraints=TaskConstraints(maxLatencyMs=5000, maxCost=.2, minQuality=.5),
                )
            )
        finally:
            await registry.stop_all()

    result = run(scenario())
    assert result.status == "COMPLETED"
    assert result.answer
    assert result.scorecard is None
    errors = [event for event in result.trace if event.kind == "eval" and event.status == "error"]
    assert len(errors) == 1
    detail = json.loads(errors[0].detail)
    assert detail == {"reason": "scorecard_unavailable", "errorType": "RuntimeError"}
    assert "fixture-scorecard-failure-secret" not in errors[0].detail


def test_hard_cost_guard_blocks_fallback_before_second_agent_attempt(monkeypatch):
    monkeypatch.setattr(engine_module.settings, "eval_scorecard_enabled", True)

    first = _agent(agent_id=1, name="Failing", endpoint="internal://fail/first", cost=.06)
    second = _agent(agent_id=2, name="Fallback", endpoint="internal://fail/second", cost=.06)

    async def scenario():
        registry = await create_registry()
        try:
            return await RuntimeEngine(registry).run(
                RuntimeRequest(
                    user_id=1,
                    request_id="evaluation-hard-cost-guard",
                    task="hello",
                    scheduler="fixed",
                    agents=[first, second],
                    constraints=TaskConstraints(maxLatencyMs=5000, maxCost=.10, minQuality=.5),
                )
            )
        finally:
            await registry.stop_all()

    with pytest.raises(DAGExecutionError) as raised:
        run(scenario())
    cause = raised.value.__cause__
    assert cause is not None
    assert "cost budget exhausted before next agent attempt" in str(cause)
