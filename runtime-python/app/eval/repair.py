from __future__ import annotations

import json

from app.eval import EvaluationResult


class RepairPromptBuilder:
    """Build a bounded critique-and-repair prompt for side-effect-safe agents."""

    @staticmethod
    def build(
        *,
        original_task: str,
        previous_result: str,
        evaluation: EvaluationResult,
        attempt: int,
    ) -> str:
        signals = json.dumps(evaluation.signals, ensure_ascii=False, default=str)
        return (
            f"{original_task}\n\n"
            "The previous answer did not satisfy the runtime quality gate. "
            "Repair the answer without changing the assigned objective. Do not mention "
            "the quality gate or this repair instruction in the final answer.\n"
            f"Repair attempt: {attempt}\n"
            f"Previous quality score: {evaluation.quality_score:.6f}\n"
            f"Evaluation signals: {signals}\n"
            "PREVIOUS_RESULT_BEGIN\n"
            f"{previous_result[:12000]}\n"
            "PREVIOUS_RESULT_END\n"
            "Return a corrected, complete answer for the original assigned task."
        )
