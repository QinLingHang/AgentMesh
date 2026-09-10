from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from app.eval.judge import Judge, JudgeRequest, JudgeResult
from app.schemas import RuntimeCitation


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    case_id: str
    task: str
    actual_answer: str
    reference_answer: str = ""
    evidence: tuple[str, ...] = ()
    citations: tuple[RuntimeCitation, ...] = ()
    tool_trace: tuple[dict[str, Any], ...] = ()
    tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EvaluationCaseResult:
    case_id: str
    judge: JudgeResult


@dataclass(frozen=True, slots=True)
class EvaluationRunResult:
    total: int
    passed: int
    failed: int
    mean_score: float
    cases: tuple[EvaluationCaseResult, ...]


async def run_evaluation_dataset(cases: Iterable[EvaluationCase], judge: Judge) -> EvaluationRunResult:
    results: list[EvaluationCaseResult] = []
    for case in cases:
        judged = await judge.evaluate(
            JudgeRequest(
                task=case.task,
                actual_answer=case.actual_answer,
                reference_answer=case.reference_answer,
                evidence=case.evidence,
                citations=case.citations,
                tool_trace=case.tool_trace,
            )
        )
        results.append(EvaluationCaseResult(case_id=case.case_id, judge=judged))
    total = len(results)
    passed = sum(1 for item in results if item.judge.passed)
    mean = sum(item.judge.score for item in results) / total if total else 0.0
    return EvaluationRunResult(
        total=total,
        passed=passed,
        failed=total - passed,
        mean_score=round(mean, 6),
        cases=tuple(results),
    )


def load_jsonl_dataset(path: str | Path) -> list[EvaluationCase]:
    result: list[EvaluationCase] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            value = json.loads(text)
            if not isinstance(value, dict):
                raise ValueError(f"dataset line {line_number} is not an object")
            result.append(
                EvaluationCase(
                    case_id=str(value.get("caseId") or value.get("case_id") or f"case-{line_number}"),
                    task=str(value.get("task") or ""),
                    actual_answer=str(value.get("actualAnswer") or value.get("actual_answer") or ""),
                    reference_answer=str(value.get("referenceAnswer") or value.get("reference_answer") or ""),
                    evidence=tuple(str(item) for item in value.get("evidence", []) if str(item).strip()),
                    citations=tuple(
                        RuntimeCitation.model_validate(item)
                        for item in value.get("citations", [])
                        if isinstance(item, dict)
                    ),
                    tool_trace=tuple(
                        dict(item)
                        for item in (value.get("toolTrace") or value.get("tool_trace") or [])
                        if isinstance(item, dict)
                    ),
                    tags=tuple(str(item) for item in value.get("tags", []) if str(item).strip()),
                    metadata=dict(value.get("metadata") or {}),
                )
            )
    return result


@dataclass(frozen=True, slots=True)
class EvaluationRegression:
    case_id: str
    baseline_score: float
    candidate_score: float
    delta: float


@dataclass(frozen=True, slots=True)
class EvaluationComparison:
    baseline_mean: float
    candidate_mean: float
    mean_delta: float
    regressions: tuple[EvaluationRegression, ...]
    improvements: tuple[EvaluationRegression, ...]


def compare_evaluation_runs(
    baseline: EvaluationRunResult,
    candidate: EvaluationRunResult,
    *,
    regression_threshold: float = 0.05,
    improvement_threshold: float = 0.05,
) -> EvaluationComparison:
    """Compare deterministic evaluation runs by case id.

    Missing cases are intentionally ignored here: dataset membership validation belongs
    to the caller so a partial exploratory run is not silently treated as a regression.
    """
    baseline_by_id = {item.case_id: item.judge.score for item in baseline.cases}
    candidate_by_id = {item.case_id: item.judge.score for item in candidate.cases}

    regressions: list[EvaluationRegression] = []
    improvements: list[EvaluationRegression] = []
    for case_id in sorted(baseline_by_id.keys() & candidate_by_id.keys()):
        before = float(baseline_by_id[case_id])
        after = float(candidate_by_id[case_id])
        delta = round(after - before, 6)
        record = EvaluationRegression(
            case_id=case_id,
            baseline_score=before,
            candidate_score=after,
            delta=delta,
        )
        if delta <= -abs(regression_threshold):
            regressions.append(record)
        elif delta >= abs(improvement_threshold):
            improvements.append(record)

    return EvaluationComparison(
        baseline_mean=baseline.mean_score,
        candidate_mean=candidate.mean_score,
        mean_delta=round(candidate.mean_score - baseline.mean_score, 6),
        regressions=tuple(regressions),
        improvements=tuple(improvements),
    )
