from __future__ import annotations

import re

from app.eval.contracts import (
    EvaluationRequest,
    EvaluationResult,
)


class HeuristicEvaluator:
    """
    Deterministic quality evaluator baseline.

    注意：

    它不是“真正的语义正确率 Judge”。

    当前只提供低成本、稳定、可重复的
    quality proxy，主要用于：

    - Runtime baseline
    - Capability Profile feedback
    - Adaptive Scheduler
    - Multi-objective Planner
    - 后续和 LLM Judge 对照
    """

    name = "heuristic"

    async def evaluate(
        self,
        request: EvaluationRequest,
    ) -> EvaluationResult:
        result = (
            request.result
            .strip()
        )

        if not result:
            return EvaluationResult(
                quality_score=0.0,
                evaluator=self.name,
                signals={
                    "empty_result": True,
                    "length": 0,
                    "task_overlap": 0.0,
                },
            )

        length_score = min(
            len(result) / 400.0,
            1.0,
        )

        task_tokens = self._tokens(
            request.task
        )

        result_tokens = self._tokens(
            result
        )

        if task_tokens:
            overlap = (
                len(
                    task_tokens
                    & result_tokens
                )
                / len(
                    task_tokens
                )
            )
        else:
            overlap = 0.0

        lower = result.lower()

        error_markers = (
            "error",
            "failed",
            "exception",
            "无法处理",
            "执行失败",
            "发生错误",
            "未知错误",
        )

        contains_error_marker = any(
            marker in lower
            for marker in error_markers
        )

        structure_bonus = (
            0.05
            if any(
                marker in result
                for marker in (
                    "\n",
                    "- ",
                    "：",
                    ": ",
                )
            )
            else 0.0
        )

        quality = (
            0.50
            + 0.20 * length_score
            + 0.25 * overlap
            + structure_bonus
        )

        if contains_error_marker:
            quality -= 0.30

        quality = min(
            max(
                quality,
                0.0,
            ),
            1.0,
        )

        return EvaluationResult(
            quality_score=round(
                quality,
                6,
            ),
            evaluator=self.name,
            signals={
                "empty_result": False,
                "length": len(
                    result
                ),
                "length_score": round(
                    length_score,
                    6,
                ),
                "task_overlap": round(
                    overlap,
                    6,
                ),
                "structure_bonus": (
                    structure_bonus
                ),
                "contains_error_marker": (
                    contains_error_marker
                ),
            },
        )

    def _tokens(
        self,
        text: str,
    ) -> set[str]:
        tokens = re.findall(
            r"[A-Za-z0-9_]+|[\u4e00-\u9fff]",
            text.lower(),
        )

        return {
            token
            for token in tokens
            if token.strip()
        }