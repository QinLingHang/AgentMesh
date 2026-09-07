from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(slots=True)
class EvaluationRequest:
    task: str
    capability: str
    result: str
    agent_name: str


@dataclass(slots=True)
class EvaluationResult:
    quality_score: float

    evaluator: str

    signals: dict[
        str,
        float | int | str | bool,
    ] = field(
        default_factory=dict
    )


@runtime_checkable
class Evaluator(Protocol):
    async def evaluate(
        self,
        request: EvaluationRequest,
    ) -> EvaluationResult:
        ...