from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agents.capability import apply_capability_feedback
from app.kernel import RuntimeContext
from app.models.runtime import ModelRuntimeResolver
from app.optimization import (
    AdaptiveAgentRouter,
    AdaptiveModelRouter,
    ModelPerformanceStore,
    compare_agent_routing_policies,
    objective_weights,
)
from app.plugins.schedulers import AdaptiveSchedulerPlugin
from app.schemas import (
    AgentCapabilityProfile,
    AgentFeedback,
    AgentProfile,
    RuntimeRequest,
    TaskConstraints,
    TaskProfile,
)
from app.services import RuntimeEngine, create_registry
from app.services.rescheduler import RuntimeRescheduler


def profile(*, complexity: str = "medium", risk: str = "medium") -> TaskProfile:
    return TaskProfile(
        required_capabilities=["general"],
        complexity=complexity,
        risk_level=risk,
        modality=["text"],
        parallelizable=False,
    )


def constraints(
    *,
    latency: int = 10_000,
    cost: float = 0.20,
    quality: float = 0.70,
) -> TaskConstraints:
    return TaskConstraints(
        maxLatencyMs=latency,
        maxCost=cost,
        minQuality=quality,
    )


def agent(
    agent_id: int,
    name: str,
    *,
    quality: float,
    reliability: float,
    latency: int,
    cost: float,
    samples: int = 30,
    load: float = 0.10,
    endpoint: str = "internal://success",
) -> AgentProfile:
    return AgentProfile(
        id=agent_id,
        name=name,
        endpoint=endpoint,
        protocol="internal",
        capabilities=["general"],
        currentLoad=load,
        status="ACTIVE",
        qualityScore=quality,
        successRate=reliability,
        avgLatencyMs=latency,
        avgCost=cost,
        capabilityProfiles=[
            AgentCapabilityProfile(
                capability="general",
                qualityScore=quality,
                successRate=reliability,
                failureRate=1.0 - reliability,
                avgLatencyMs=latency,
                avgCost=cost,
                sampleCount=samples,
            )
        ],
    )


def quality_agent() -> AgentProfile:
    return agent(
        1,
        "QualityAgent",
        quality=0.95,
        reliability=0.95,
        latency=8_000,
        cost=0.18,
    )


def fast_agent() -> AgentProfile:
    return agent(
        2,
        "FastCheapAgent",
        quality=0.80,
        reliability=0.85,
        latency=300,
        cost=0.002,
    )


def test_task_aware_agent_routing_changes_objective_preference():
    router = AdaptiveAgentRouter()
    agents = [quality_agent(), fast_agent()]
    limits = constraints()

    high = router.route(
        agents=agents,
        capability="general",
        profile=profile(complexity="high", risk="high"),
        constraints=limits,
    )
    low = router.route(
        agents=agents,
        capability="general",
        profile=profile(complexity="low", risk="low"),
        constraints=limits,
    )

    assert high.selected_agent_name == "QualityAgent"
    assert low.selected_agent_name == "FastCheapAgent"
    assert high.weights.quality > low.weights.quality
    assert low.weights.latency > high.weights.latency
    assert low.weights.cost > high.weights.cost


def test_historical_capability_feedback_changes_later_route():
    router = AdaptiveAgentRouter()
    first = agent(1, "AgentA", quality=0.93, reliability=0.95, latency=900, cost=0.01)
    second = agent(2, "AgentB", quality=0.84, reliability=0.88, latency=900, cost=0.01)
    limits = constraints(quality=0.70)
    task = profile()

    before = router.route(
        agents=[first, second],
        capability="general",
        profile=task,
        constraints=limits,
    )
    assert before.selected_agent_id == first.id

    apply_capability_feedback(
        first,
        AgentFeedback(
            agentId=first.id,
            capability="general",
            success=False,
            latencyMs=8_000,
            cost=0.10,
            qualityScore=0.40,
        ),
        alpha=1.0,
    )
    apply_capability_feedback(
        second,
        AgentFeedback(
            agentId=second.id,
            capability="general",
            success=True,
            latencyMs=400,
            cost=0.002,
            qualityScore=0.98,
        ),
        alpha=1.0,
    )

    after = router.route(
        agents=[first, second],
        capability="general",
        profile=task,
        constraints=limits,
    )
    assert after.selected_agent_id == second.id


def test_feasible_candidates_are_preferred_over_higher_raw_infeasible_candidate():
    router = AdaptiveAgentRouter()
    infeasible = agent(
        1,
        "SlowExcellent",
        quality=0.99,
        reliability=1.0,
        latency=9_000,
        cost=0.01,
    )
    feasible = agent(
        2,
        "FeasibleAgent",
        quality=0.80,
        reliability=0.80,
        latency=500,
        cost=0.01,
    )
    decision = router.route(
        agents=[infeasible, feasible],
        capability="general",
        profile=profile(complexity="high", risk="high"),
        constraints=constraints(latency=1_000, cost=0.05, quality=0.75),
    )
    assert decision.selected_agent_id == feasible.id
    assert decision.degraded is False
    assert next(item for item in decision.candidates if item.agent_id == infeasible.id).feasible is False


def test_all_infeasible_candidates_are_explicitly_degraded_and_deterministic():
    router = AdaptiveAgentRouter()
    agents = [
        agent(2, "Second", quality=0.80, reliability=0.80, latency=2_000, cost=0.02),
        agent(1, "First", quality=0.80, reliability=0.80, latency=2_000, cost=0.02),
    ]
    decision = router.route(
        agents=agents,
        capability="general",
        profile=profile(),
        constraints=constraints(latency=100, cost=0.001, quality=0.99),
    )
    assert decision.degraded is True
    assert all(item.feasible is False for item in decision.candidates)
    # Equal candidates use the lower Agent id as the stable tie break.
    assert decision.selected_agent_id == 1


def test_used_agent_is_avoided_when_an_alternative_exists():
    router = AdaptiveAgentRouter()
    first = agent(1, "First", quality=0.90, reliability=0.90, latency=500, cost=0.01)
    second = agent(2, "Second", quality=0.90, reliability=0.90, latency=500, cost=0.01)
    decision = router.route(
        agents=[first, second],
        capability="general",
        profile=profile(),
        constraints=constraints(),
        used_agent_ids={1},
    )
    assert decision.selected_agent_id == 2


def test_exploration_bonus_is_bounded_and_favours_cold_start():
    router = AdaptiveAgentRouter()
    newcomer = agent(1, "New", quality=0.90, reliability=0.90, latency=500, cost=0.01, samples=0)
    experienced = agent(2, "Old", quality=0.90, reliability=0.90, latency=500, cost=0.01, samples=100)
    decision = router.route(
        agents=[experienced, newcomer],
        capability="general",
        profile=profile(complexity="low", risk="low"),
        constraints=constraints(),
    )
    by_id = {item.agent_id: item for item in decision.candidates}
    assert by_id[newcomer.id].exploration_bonus > by_id[experienced.id].exploration_bonus
    assert by_id[newcomer.id].exploration_bonus <= decision.weights.exploration


class FakeRuntime:
    def __init__(
        self,
        *,
        provider: str,
        model: str,
        quality: float,
        reliability: float,
        latency: int,
        cost: float,
        samples: int = 30,
    ) -> None:
        self.provider = provider
        self.model = model
        self.routing_quality_score = quality
        self.routing_success_rate = reliability
        self.routing_avg_latency_ms = latency
        self.routing_avg_cost = cost
        self.routing_sample_count = samples
        self.gateway = SimpleNamespace()


def model_context() -> RuntimeContext:
    context = RuntimeContext()
    context.provide(
        "model.runtime.quality",
        FakeRuntime(
            provider="quality-provider",
            model="quality-model",
            quality=0.95,
            reliability=0.95,
            latency=8_000,
            cost=0.18,
        ),
    )
    context.provide(
        "model.runtime.fast",
        FakeRuntime(
            provider="fast-provider",
            model="fast-model",
            quality=0.80,
            reliability=0.85,
            latency=300,
            cost=0.002,
        ),
    )
    return context


def test_task_aware_adaptive_model_routing_selects_different_runtime():
    router = AdaptiveModelRouter(model_context())
    limits = constraints()

    high = router.route(
        preferred_runtime="adaptive",
        profile=profile(complexity="high", risk="high"),
        constraints=limits,
    )
    low = router.route(
        preferred_runtime="adaptive",
        profile=profile(complexity="low", risk="low"),
        constraints=limits,
    )

    assert high.selected_runtime_id == "quality"
    assert low.selected_runtime_id == "fast"
    assert high.mode == "adaptive"
    assert low.mode == "adaptive"


def test_model_router_pinned_route_remains_pinned():
    router = AdaptiveModelRouter(model_context())
    decision = router.route(
        preferred_runtime="quality",
        profile=profile(complexity="low", risk="low"),
        constraints=constraints(),
    )
    assert decision.mode == "pinned"
    assert decision.selected_runtime_id == "quality"
    assert len(decision.candidates) == 1


def test_model_performance_store_updates_execution_and_quality_ewma():
    plugin = FakeRuntime(
        provider="p",
        model="m",
        quality=0.80,
        reliability=1.0,
        latency=1_000,
        cost=0.01,
        samples=0,
    )
    store = ModelPerformanceStore(alpha=0.5)
    store.record_execution(
        "runtime-a",
        plugin,
        success=False,
        latency_ms=2_000,
        cost=0.03,
    )
    store.record_quality("runtime-a", plugin, 0.40)
    item = store.get_or_seed("runtime-a", plugin)
    assert item.success_rate == pytest.approx(0.5)
    assert item.avg_latency_ms == 1_500
    assert item.avg_cost == pytest.approx(0.02)
    assert item.quality_score == pytest.approx(0.60)
    assert item.sample_count == 1


def test_model_router_failure_falls_back_to_declared_default(monkeypatch):
    context = RuntimeContext()
    default = FakeRuntime(
        provider="default-provider",
        model="default-model",
        quality=0.8,
        reliability=1.0,
        latency=500,
        cost=0.01,
    )
    context.provide("model.runtime.default", default)
    resolver = ModelRuntimeResolver(context)

    def explode(**_kwargs):
        raise RuntimeError("router unavailable")

    monkeypatch.setattr(resolver.model_router, "route", explode)
    resolved = resolver.resolve(
        AgentProfile(
            id=10,
            name="AdaptiveAgent",
            endpoint="internal://success",
            protocol="internal",
            capabilities=["general"],
            modelRuntime="adaptive",
        ),
        adaptive=True,
        constraints=constraints(),
        profile=profile(),
    )
    assert resolved.runtime_id == "default"
    assert resolved.model == "default-model"
    assert resolved.route_decision is None


def test_rescheduler_reuses_adaptive_router_policy():
    candidates = [quality_agent(), fast_agent()]
    task = profile(complexity="low", risk="low")
    limits = constraints()
    expected = AdaptiveAgentRouter().route(
        agents=candidates,
        capability="general",
        profile=task,
        constraints=limits,
    )
    replacement = RuntimeRescheduler().choose_replacement(
        agents=candidates,
        capability="general",
        constraints=limits,
        attempted_agent_ids=set(),
        profile=task,
    )
    assert replacement is not None
    assert replacement.agent.id == expected.selected_agent_id
    assert replacement.reason == expected.reason
    assert replacement.candidates


def test_routing_decision_contract_is_metadata_only():
    decision = AdaptiveAgentRouter().route(
        agents=[quality_agent(), fast_agent()],
        capability="general",
        profile=profile(),
        constraints=constraints(),
    ).as_dict()
    payload = json.dumps(decision, ensure_ascii=False).lower()
    for forbidden in (
        "rawtask",
        "tasktext",
        "memorycontent",
        "ragevidence",
        "toolresult",
        "password",
        "credential",
        "otp",
    ):
        assert forbidden not in payload


def test_offline_adaptive_routing_cases_parse_and_exercise_policy_comparison():
    path = Path(__file__).resolve().parents[1] / "evals" / "adaptive_routing_cases.jsonl"
    cases = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert {case["id"] for case in cases} == {"quality_first", "fast_cheap", "degraded_constraints"}

    agents = [quality_agent(), fast_agent()]
    degraded_seen = False
    for case in cases:
        task = TaskProfile(
            required_capabilities=["general"],
            complexity=case["complexity"],
            risk_level=case["riskLevel"],
            modality=["text"],
            parallelizable=False,
        )
        limits = TaskConstraints(
            maxLatencyMs=case["maxLatencyMs"],
            maxCost=case["maxCost"],
            minQuality=case["minQuality"],
        )
        comparison = compare_agent_routing_policies(
            agents=agents,
            profile=task,
            constraints=limits,
        )
        assert len(comparison) == 1
        if case["expected"] == "best_effort_degraded":
            assert comparison[0].degraded is True
            degraded_seen = True
        elif case["expected"] == "quality_reliability_weighted":
            weights = objective_weights(task)
            assert weights.quality + weights.reliability > weights.latency + weights.cost
        elif case["expected"] == "latency_cost_weighted":
            weights = objective_weights(task)
            high = objective_weights(profile(complexity="high", risk="high"))
            assert weights.latency + weights.cost > high.latency + high.cost
    assert degraded_seen


@pytest.mark.asyncio
async def test_adaptive_runtime_emits_agent_model_and_feedback_routing_trace():
    registry = await create_registry()
    try:
        engine = RuntimeEngine(registry)
        result = await engine.run(
            RuntimeRequest(
                user_id=1,
                request_id="adaptive-routing-trace",
                task="Explain what an AI Agent is.",
                scheduler="adaptive",
                agents=[
                    agent(
                        99,
                        "TraceAgent",
                        quality=0.90,
                        reliability=0.95,
                        latency=500,
                        cost=0.01,
                        endpoint="internal://success",
                    )
                ],
            )
        )
        routing = [item for item in result.trace if item.kind == "routing"]
        model_routes = [item for item in result.trace if item.kind == "model_route"]
        assert any(item.title == "Adaptive Agent Route" for item in routing)
        assert model_routes
        model_detail = json.loads(model_routes[0].detail)
        assert model_detail["mode"] == "adaptive"
        assert "candidates" in model_detail
        assert any(item.title == "Model Route Feedback" for item in routing)
    finally:
        await registry.stop_all()


@pytest.mark.asyncio
async def test_fixed_scheduler_keeps_legacy_model_route_mode():
    registry = await create_registry()
    try:
        engine = RuntimeEngine(registry)
        result = await engine.run(
            RuntimeRequest(
                user_id=1,
                request_id="adaptive-fixed-route",
                task="Explain what an AI Agent is.",
                scheduler="fixed",
                agents=[
                    agent(
                        100,
                        "LegacyAgent",
                        quality=0.90,
                        reliability=0.95,
                        latency=500,
                        cost=0.01,
                        endpoint="internal://success",
                    )
                ],
            )
        )
        model_routes = [item for item in result.trace if item.kind == "model_route"]
        assert model_routes
        detail = json.loads(model_routes[0].detail)
        assert detail["mode"] == "declared"
        assert detail["candidates"] == []
    finally:
        await registry.stop_all()
