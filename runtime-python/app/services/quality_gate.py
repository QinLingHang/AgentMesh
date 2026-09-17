from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.eval import EvaluationResult


QualityAction = Literal["pass", "repair", "degraded", "fail"]


class QualityGateError(RuntimeError):
    def __init__(self, message: str, *, score: float) -> None:
        super().__init__(message)
        self.score = score


@dataclass(slots=True)
class QualityGateDecision:
    action: QualityAction
    score: float
    reason: str


class QualityGate:
    """Convert evaluator telemetry into bounded runtime control decisions."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        pass_threshold: float = 0.58,
        hard_fail_threshold: float = 0.20,
        max_repair_attempts: int = 1,
    ) -> None:
        self.enabled = bool(enabled)
        self.pass_threshold = min(max(float(pass_threshold), 0.0), 1.0)
        self.hard_fail_threshold = min(max(float(hard_fail_threshold), 0.0), 1.0)
        self.max_repair_attempts = max(0, int(max_repair_attempts))

    def decide(
        self,
        evaluation: EvaluationResult,
        *,
        repair_attempts: int,
        allow_repair: bool,
    ) -> QualityGateDecision:
        score = float(evaluation.quality_score)
        if not self.enabled:
            return QualityGateDecision("pass", score, "quality gate disabled")

        empty = bool(evaluation.signals.get("empty_result", False))
        has_error = bool(evaluation.signals.get("contains_error_marker", False))

        if score >= self.pass_threshold and not empty:
            return QualityGateDecision("pass", score, "quality threshold satisfied")

        if allow_repair and repair_attempts < self.max_repair_attempts:
            reason = "empty result" if empty else "quality below threshold"
            return QualityGateDecision("repair", score, reason)

        if empty or score < self.hard_fail_threshold:
            return QualityGateDecision(
                "fail",
                score,
                "hard quality floor rejected the result" if not empty else "empty result rejected",
            )

        if has_error and score < self.pass_threshold:
            return QualityGateDecision("degraded", score, "error marker detected but hard floor not crossed")

        return QualityGateDecision("degraded", score, "quality below preferred threshold")
