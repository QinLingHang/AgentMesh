from __future__ import annotations

from dataclasses import dataclass

from app.schemas import RunScorecard


@dataclass(slots=True)
class BaselineComparison:
    current_mean: float
    baseline_mean: float
    delta: float
    regressed: bool


def compare_scorecards(
    current: list[RunScorecard],
    baseline_mean: float,
    *,
    regression_tolerance: float = 0.03,
) -> BaselineComparison:
    """Small offline-regression primitive used by CI/eval datasets."""
    mean = (
        sum(item.overall_score for item in current) / len(current)
        if current
        else 0.0
    )
    delta = mean - baseline_mean
    return BaselineComparison(
        current_mean=round(mean, 6),
        baseline_mean=round(baseline_mean, 6),
        delta=round(delta, 6),
        regressed=delta < -abs(regression_tolerance),
    )
