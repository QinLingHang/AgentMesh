from __future__ import annotations

from math import sqrt
from typing import Any

from app.kernel import RuntimeContext
from app.optimization.contracts import (
    ModelCandidateScore,
    ModelRouteDecision,
    ModelRuntimeMetrics,
)
from app.optimization.policy import objective_weights
from app.schemas import TaskConstraints, TaskProfile


def _budget_score(value: float, limit: float) -> float:
    if limit <= 0:
        return 1.0
    ratio = max(0.0, value) / max(limit, 1e-9)
    return max(0.0, 1.0 - min(ratio, 2.0) / 2.0)


class ModelPerformanceStore:
    """Process-local EWMA telemetry for Model runtimes.

    Agent historical metrics are persisted in Go/MySQL. Model telemetry is
    intentionally process-local in Adaptive Routing: it adapts during the Runtime lifetime
    without introducing a second persistence subsystem. A later control-plane
    phase can persist this same contract if cross-restart model learning is
    required.
    """

    def __init__(self, alpha: float = 0.2) -> None:
        self.alpha = min(max(alpha, 0.01), 1.0)
        self._items: dict[str, ModelRuntimeMetrics] = {}

    def get_or_seed(self, runtime_id: str, plugin: Any) -> ModelRuntimeMetrics:
        existing = self._items.get(runtime_id)
        if existing is not None:
            return existing
        item = ModelRuntimeMetrics(
            runtime_id=runtime_id,
            quality_score=float(getattr(plugin, "routing_quality_score", 0.8)),
            avg_latency_ms=max(1, int(getattr(plugin, "routing_avg_latency_ms", 1000))),
            avg_cost=max(0.0, float(getattr(plugin, "routing_avg_cost", 0.0))),
            success_rate=min(max(float(getattr(plugin, "routing_success_rate", 1.0)), 0.0), 1.0),
            sample_count=max(0, int(getattr(plugin, "routing_sample_count", 0))),
        )
        self._items[runtime_id] = item
        return item

    def record_execution(
        self,
        runtime_id: str,
        plugin: Any,
        *,
        success: bool,
        latency_ms: int,
        cost: float | None,
    ) -> None:
        item = self.get_or_seed(runtime_id, plugin)
        alpha = self.alpha
        item.success_rate = round(
            (1.0 - alpha) * item.success_rate + alpha * (1.0 if success else 0.0),
            6,
        )
        if latency_ms > 0:
            item.avg_latency_ms = max(
                1,
                int(round((1.0 - alpha) * item.avg_latency_ms + alpha * latency_ms)),
            )
        if cost is not None:
            item.avg_cost = round(
                (1.0 - alpha) * item.avg_cost + alpha * max(0.0, float(cost)),
                8,
            )
        item.sample_count += 1

    def record_quality(self, runtime_id: str, plugin: Any, quality: float) -> None:
        item = self.get_or_seed(runtime_id, plugin)
        item.quality_score = round(
            (1.0 - self.alpha) * item.quality_score
            + self.alpha * min(max(float(quality), 0.0), 1.0),
            6,
        )


class AdaptiveModelRouter:
    def __init__(self, context: RuntimeContext) -> None:
        self.context = context
        self.performance = ModelPerformanceStore()

    def _runtimes(self) -> list[tuple[str, Any]]:
        out: list[tuple[str, Any]] = []
        for key, plugin in self.context.services.items():
            if not key.startswith("model.runtime."):
                continue
            runtime_id = key.removeprefix("model.runtime.")
            out.append((runtime_id, plugin))
        return sorted(out, key=lambda item: item[0])

    def route(
        self,
        *,
        preferred_runtime: str,
        profile: TaskProfile,
        constraints: TaskConstraints,
    ) -> ModelRouteDecision:
        return self.route_candidates(
            runtimes=self._runtimes(),
            preferred_runtime=preferred_runtime,
            profile=profile,
            constraints=constraints,
        )

    def route_candidates(
        self,
        *,
        runtimes: list[tuple[str, Any]],
        preferred_runtime: str,
        profile: TaskProfile,
        constraints: TaskConstraints,
    ) -> ModelRouteDecision:
        """Route across an explicit runtime set.

        Adaptive Routing originally routed only process-global model plugins registered in the
        RuntimeContext. The user BYOK model pool is request-local by design, so
        this method reuses the exact same scoring/performance store without
        mutating global runtime state or leaking credentials between users.
        """
        if not runtimes:
            raise RuntimeError("no model runtime is registered")

        preferred = preferred_runtime.strip().lower() or "default"
        by_id = {runtime_id: plugin for runtime_id, plugin in runtimes}
        if preferred not in {"adaptive", "auto", "default"}:
            if preferred not in by_id:
                raise RuntimeError(f"model runtime is not registered: {preferred}")
            plugin = by_id[preferred]
            metrics = self.performance.get_or_seed(preferred, plugin)
            candidate = self._score_candidate(preferred, plugin, metrics, profile, constraints)
            return ModelRouteDecision(
                selected_runtime_id=preferred,
                selected_provider=str(getattr(plugin, "provider", "unknown")),
                selected_model=str(getattr(plugin, "model", "")),
                selected_score=candidate.score,
                degraded=not candidate.feasible,
                mode="pinned",
                reason="request explicitly pinned a model runtime",
                weights=objective_weights(profile),
                candidates=[candidate],
            )

        scored = [
            self._score_candidate(
                runtime_id,
                plugin,
                self.performance.get_or_seed(runtime_id, plugin),
                profile,
                constraints,
            )
            for runtime_id, plugin in runtimes
        ]
        feasible = [item for item in scored if item.feasible]
        pool = feasible or scored

        def selection_key(item: ModelCandidateScore) -> tuple[float, bool, str]:
            plugin = by_id[item.runtime_id]
            preferred_default = bool(getattr(plugin, "routing_is_default", False)) or item.runtime_id == "default"
            return item.score, preferred_default, item.runtime_id

        selected = max(pool, key=selection_key)
        plugin = by_id[selected.runtime_id]
        return ModelRouteDecision(
            selected_runtime_id=selected.runtime_id,
            selected_provider=str(getattr(plugin, "provider", "unknown")),
            selected_model=str(getattr(plugin, "model", "")),
            selected_score=selected.score,
            degraded=not bool(feasible),
            mode="adaptive",
            reason=(
                "best feasible model runtime for current quality/cost/latency policy"
                if feasible
                else "no model runtime satisfied every constraint; selected best-effort runtime"
            ),
            weights=objective_weights(profile),
            candidates=sorted(scored, key=lambda item: (-item.score, item.runtime_id)),
        )

    def _score_candidate(
        self,
        runtime_id: str,
        plugin: Any,
        metrics: ModelRuntimeMetrics,
        profile: TaskProfile,
        constraints: TaskConstraints,
    ) -> ModelCandidateScore:
        weights = objective_weights(profile)
        quality = min(max(metrics.quality_score, 0.0), 1.0)
        reliability = min(max(metrics.success_rate, 0.0), 1.0)
        latency_score = _budget_score(float(metrics.avg_latency_ms), float(constraints.max_latency_ms))
        cost_score = _budget_score(float(metrics.avg_cost), float(constraints.max_cost))
        exploration = 1.0 / sqrt(metrics.sample_count + 1.0)

        violations: list[str] = []
        if quality < constraints.min_quality:
            violations.append("quality")
        if metrics.avg_latency_ms > constraints.max_latency_ms:
            violations.append("latency")
        if constraints.max_cost > 0 and metrics.avg_cost > constraints.max_cost:
            violations.append("cost")

        # Model routing has no current-load signal, so redistribute the Agent
        # load weight to reliability. This keeps the same task-aware policy.
        score = (
            weights.quality * quality
            + (weights.reliability + weights.load) * reliability
            + weights.latency * latency_score
            + weights.cost * cost_score
            + weights.exploration * exploration
        )
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

        return ModelCandidateScore(
            runtime_id=runtime_id,
            provider=str(getattr(plugin, "provider", "unknown")),
            model=str(getattr(plugin, "model", "")),
            score=score,
            feasible=not violations,
            quality=quality,
            reliability=reliability,
            latency_ms=metrics.avg_latency_ms,
            avg_cost=metrics.avg_cost,
            sample_count=metrics.sample_count,
            exploration_bonus=weights.exploration * exploration,
            constraint_violations=violations,
            reasons=reasons,
        )
