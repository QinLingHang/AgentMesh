from __future__ import annotations

import asyncio
import json
from typing import Any, Callable

from app.planning.contracts import ExecutionPlan, PlanStep
from app.planning.planner import SemanticTaskPlanner
from app.planning.validator import PlanValidator


class SemanticReplanner:
    """Bounded model-assisted replanner for side-effect-safe executions.

    The caller decides whether replanning is safe.  Completed steps are supplied
    to the validator and are preserved exactly so their work is never replayed.
    """

    def __init__(
        self,
        *,
        validator: PlanValidator,
        timeout_seconds: float = 12.0,
    ) -> None:
        self.validator = validator
        self.timeout_seconds = max(1.0, float(timeout_seconds))

    async def replan(
        self,
        *,
        task: str,
        current_plan: ExecutionPlan,
        completed_steps: dict[str, PlanStep],
        failed_step_id: str | None,
        failure: BaseException,
        available_capabilities: set[str],
        baseline_capabilities: list[str],
        model: Any | None,
        on_model_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> ExecutionPlan | None:
        if model is None:
            return None

        prompt = self._build_prompt(
            task=task,
            current_plan=current_plan,
            completed_steps=completed_steps,
            failed_step_id=failed_step_id,
            failure=failure,
            available_capabilities=available_capabilities,
        )

        try:
            raw = await asyncio.wait_for(
                model.generate(prompt, on_model_event),
                timeout=self.timeout_seconds,
            )
            candidate = SemanticTaskPlanner._parse_plan(raw, source="replan_model")
            validated = self.validator.validate(
                candidate,
                available_capabilities=available_capabilities,
                baseline_capabilities=baseline_capabilities,
                completed_steps=completed_steps,
            )
        except Exception:
            return None

        if self._canonical(validated) == self._canonical(current_plan):
            return None
        return validated

    @staticmethod
    def _canonical(plan: ExecutionPlan) -> str:
        return json.dumps(
            plan.model_dump(by_alias=True, exclude={"source", "reason"}),
            ensure_ascii=False,
            sort_keys=True,
        )

    @staticmethod
    def _build_prompt(
        *,
        task: str,
        current_plan: ExecutionPlan,
        completed_steps: dict[str, PlanStep],
        failed_step_id: str | None,
        failure: BaseException,
        available_capabilities: set[str],
    ) -> str:
        completed = sorted(completed_steps)
        failure_summary = f"{type(failure).__name__}: {str(failure)[:1000]}"
        return (
            "You are the AgentMesh bounded replanner. Produce JSON only.\n"
            "Revise only the unfinished part of the plan. Completed step IDs must remain "
            "present and unchanged. Do not select concrete Agent IDs/names. Use only the "
            "available capabilities. Keep the graph acyclic and minimal.\n"
            "Schema: {\"goal\":\"...\",\"requiresSynthesis\":true,\"steps\":["
            "{\"id\":\"...\",\"objective\":\"...\",\"capability\":\"...\","
            "\"dependsOn\":[],\"optional\":false,\"condition\":null}]}\n"
            f"AVAILABLE_CAPABILITIES={json.dumps(sorted(available_capabilities), ensure_ascii=False)}\n"
            f"COMPLETED_STEP_IDS={json.dumps(completed, ensure_ascii=False)}\n"
            f"FAILED_STEP_ID={json.dumps(failed_step_id, ensure_ascii=False)}\n"
            f"FAILURE={json.dumps(failure_summary, ensure_ascii=False)}\n"
            f"CURRENT_PLAN={current_plan.model_dump_json(by_alias=True)}\n"
            "USER_GOAL_BEGIN\n"
            f"{task}\n"
            "USER_GOAL_END"
        )
