from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class ObjectiveWeights:
    quality: float
    reliability: float
    latency: float
    cost: float
    load: float
    exploration: float

    def as_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass(slots=True)
class AgentCandidateScore:
    agent_id: int
    agent_name: str
    capability: str
    score: float
    feasible: bool
    quality: float
    reliability: float
    latency_ms: int
    avg_cost: float
    load: float
    sample_count: int
    exploration_bonus: float
    constraint_violations: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "agentId": self.agent_id,
            "agentName": self.agent_name,
            "capability": self.capability,
            "score": round(self.score, 6),
            "feasible": self.feasible,
            "quality": round(self.quality, 6),
            "reliability": round(self.reliability, 6),
            "latencyMs": self.latency_ms,
            "avgCost": round(self.avg_cost, 8),
            "load": round(self.load, 6),
            "sampleCount": self.sample_count,
            "explorationBonus": round(self.exploration_bonus, 6),
            "constraintViolations": list(self.constraint_violations),
            "reasons": list(self.reasons),
        }


@dataclass(slots=True)
class AgentRouteDecision:
    capability: str
    selected_agent_id: int
    selected_agent_name: str
    selected_score: float
    degraded: bool
    weights: ObjectiveWeights
    reason: str
    candidates: list[AgentCandidateScore]

    def as_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "selectedAgentId": self.selected_agent_id,
            "selectedAgentName": self.selected_agent_name,
            "selectedScore": round(self.selected_score, 6),
            "degraded": self.degraded,
            "weights": self.weights.as_dict(),
            "reason": self.reason,
            "candidates": [item.as_dict() for item in self.candidates],
        }


@dataclass(slots=True)
class ModelRuntimeMetrics:
    runtime_id: str
    quality_score: float = 0.8
    avg_latency_ms: int = 1000
    avg_cost: float = 0.0
    success_rate: float = 1.0
    sample_count: int = 0


@dataclass(slots=True)
class ModelCandidateScore:
    runtime_id: str
    provider: str
    model: str
    score: float
    feasible: bool
    quality: float
    reliability: float
    latency_ms: int
    avg_cost: float
    sample_count: int
    exploration_bonus: float
    constraint_violations: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "runtimeId": self.runtime_id,
            "provider": self.provider,
            "model": self.model,
            "score": round(self.score, 6),
            "feasible": self.feasible,
            "quality": round(self.quality, 6),
            "reliability": round(self.reliability, 6),
            "latencyMs": self.latency_ms,
            "avgCost": round(self.avg_cost, 8),
            "sampleCount": self.sample_count,
            "explorationBonus": round(self.exploration_bonus, 6),
            "constraintViolations": list(self.constraint_violations),
            "reasons": list(self.reasons),
        }


@dataclass(slots=True)
class ModelRouteDecision:
    selected_runtime_id: str
    selected_provider: str
    selected_model: str
    selected_score: float
    degraded: bool
    mode: str
    reason: str
    weights: ObjectiveWeights
    candidates: list[ModelCandidateScore]

    def as_dict(self) -> dict[str, Any]:
        return {
            "selectedRuntimeId": self.selected_runtime_id,
            "selectedProvider": self.selected_provider,
            "selectedModel": self.selected_model,
            "selectedScore": round(self.selected_score, 6),
            "degraded": self.degraded,
            "mode": self.mode,
            "reason": self.reason,
            "weights": self.weights.as_dict(),
            "candidates": [item.as_dict() for item in self.candidates],
        }
