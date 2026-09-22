from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Callable

from app.planning.contracts import ExecutionPlan, PlanStep, SemanticPlanningOutcome
from app.planning.validator import PlanValidationError, PlanValidator
from app.schemas import AgentProfile, TaskProfile
from app.semantics.contracts import TaskSemanticIntent


class SemanticTaskPlanner:
    """Model-assisted semantic planner with deterministic fail-safe fallback."""

    _SEQUENTIAL_MARKERS = (
        "然后",
        "接着",
        "随后",
        "之后",
        "最后",
        "最终",
        "再根据",
        "并根据",
        "根据",
        "基于上述",
        "基于前面",
        "then",
        "after that",
        "finally",
        "based on",
    )

    _COORDINATION_MARKERS = (
        "分别",
        "同时",
        "并行",
        "并且",
        "以及",
        "并根据",
        "根据",
        "然后",
        "接着",
        "随后",
        "之后",
        "最后",
        "最终",
        "综合",
        "基于",
        "依赖",
        "and then",
        "then",
        "finally",
        "based on",
        "compare",
        "compare with",
    )

    def __init__(
        self,
        *,
        validator: PlanValidator,
        timeout_seconds: float = 12.0,
    ) -> None:
        self.validator = validator
        self.timeout_seconds = max(1.0, float(timeout_seconds))

    def should_plan(self, *, task: str, profile: TaskProfile) -> bool:
        """Return True only when semantic decomposition adds real value.

        Legacy scheduling already handles a single capability and simple
        independent multi-capability requests well.  Keeping those requests on
        the fast path avoids an extra model call and preserves established
        runtime behaviour.  Semantic planning is reserved for explicit
        coordination/dependency language or genuinely broad high-complexity
        requests.
        """
        lower = task.casefold()
        required_capability_count = len(
            {
                item.strip().casefold()
                for item in profile.required_capabilities
                if item and item.strip()
            }
        )
        clauses = self._split_clauses(task)
        has_coordination_marker = any(
            marker.casefold() in lower
            for marker in self._COORDINATION_MARKERS
        )

        # A high-complexity task spanning multiple trusted capabilities is
        # already a strong decomposition signal even when the user's language
        # does not contain an English-style conjunction.  This keeps Chinese
        # and other non-English requests from accidentally falling through the
        # single-agent fast path.
        if profile.complexity == "high" and required_capability_count >= 2:
            return True

        if has_coordination_marker:
            if profile.complexity in {"medium", "high"}:
                return True
            if len(clauses) >= 2:
                return True

        # Broad high-complexity requests with explicit multi-clause structure
        # should also be planned even if the profiler only exposed one generic
        # capability.
        if profile.complexity == "high" and len(clauses) >= 2:
            return True

        return False

    async def plan(
        self,
        *,
        task: str,
        profile: TaskProfile,
        agents: list[AgentProfile],
        model: Any | None,
        semantic: TaskSemanticIntent | None = None,
        on_model_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> SemanticPlanningOutcome:
        available = self.available_capabilities(agents, profile)

        if model is not None:
            try:
                raw = await asyncio.wait_for(
                    model.generate(
                        self._build_prompt(task, profile, available, semantic),
                        on_model_event,
                    ),
                    timeout=self.timeout_seconds,
                )
                parsed = self._parse_plan(raw, source="semantic_model")
                validated = self.validator.validate(
                    parsed,
                    available_capabilities=available,
                    baseline_capabilities=list(profile.required_capabilities),
                )
                return SemanticPlanningOutcome(plan=validated, used_model=True)
            except Exception as exc:
                fallback = self._deterministic_fallback(task, profile, available, semantic)
                return SemanticPlanningOutcome(
                    plan=fallback,
                    used_model=False,
                    fallback_reason=(
                        f"{type(exc).__name__}: {str(exc)[:240]}"
                    ),
                )

        return SemanticPlanningOutcome(
            plan=self._deterministic_fallback(task, profile, available, semantic),
            used_model=False,
            fallback_reason="planning model unavailable",
        )

    @staticmethod
    def available_capabilities(
        agents: list[AgentProfile],
        profile: TaskProfile,
    ) -> set[str]:
        out = {item.strip() for item in profile.required_capabilities if item.strip()}
        for agent in agents:
            out.update(item.strip() for item in agent.capabilities if item.strip())
        if not out:
            out.add("general")
        return out

    def _deterministic_fallback(
        self,
        task: str,
        profile: TaskProfile,
        available: set[str],
        semantic: TaskSemanticIntent | None = None,
    ) -> ExecutionPlan:
        capabilities = list(dict.fromkeys(profile.required_capabilities or ["general"]))
        general = next((item for item in available if item.casefold() == "general"), None)

        # When the profiler only sees a generic capability, retain useful task
        # decomposition by splitting obvious multi-part user objectives.
        clauses = self._split_clauses(task)
        if len(capabilities) == 1 and len(clauses) >= 2:
            capability = capabilities[0]
            if capability.casefold() not in {item.casefold() for item in available} and general:
                capability = general
            sequential = any(marker.casefold() in task.casefold() for marker in self._SEQUENTIAL_MARKERS)
            steps: list[PlanStep] = []
            for index, clause in enumerate(clauses[: self.validator.max_steps], start=1):
                depends = [f"step_{index - 1}"] if sequential and index > 1 else []
                steps.append(
                    PlanStep(
                        id=f"step_{index}",
                        objective=self._bounded_objective(clause),
                        capability=capability,
                        dependsOn=depends,
                        knowledgeDependency=(semantic.knowledge_dependency.value if semantic is not None else "NONE"),
                        forbiddenActions=(list(semantic.forbidden_actions) if semantic is not None else []),
                    )
                )
        else:
            steps = []
            sequential = not profile.parallelizable or profile.risk_level == "high"
            for index, capability in enumerate(capabilities[: self.validator.max_steps], start=1):
                depends = [f"step_{index - 1}"] if sequential and index > 1 else []
                steps.append(
                    PlanStep(
                        id=f"step_{index}",
                        objective=self._bounded_objective(
                            f"Handle '{capability}' for the user goal: {task}"
                        ),
                        capability=capability,
                        dependsOn=depends,
                        knowledgeDependency=(semantic.knowledge_dependency.value if semantic is not None else "NONE"),
                        forbiddenActions=(list(semantic.forbidden_actions) if semantic is not None else []),
                    )
                )

        plan = ExecutionPlan(
            goal=task[:20000],
            steps=steps or [
                PlanStep(
                    id="step_1",
                    objective=self._bounded_objective(task),
                    capability="general",
                    knowledgeDependency=(semantic.knowledge_dependency.value if semantic is not None else "NONE"),
                    forbiddenActions=(list(semantic.forbidden_actions) if semantic is not None else []),
                )
            ],
            requiresSynthesis=len(steps) > 1,
            source="deterministic_fallback",
            reason="semantic planner fallback",
        )
        return self.validator.validate(
            plan,
            available_capabilities=available,
            baseline_capabilities=list(profile.required_capabilities),
        )

    @staticmethod
    def _bounded_objective(value: str, limit: int = 4000) -> str:
        text = str(value or "").strip()
        if not text:
            return "Handle the assigned user goal."
        if len(text) <= limit:
            return text
        return text[: max(1, limit - 24)].rstrip() + "\n[objective truncated]"

    @staticmethod
    def _split_clauses(task: str) -> list[str]:
        # First split punctuation only when it introduces an explicit
        # coordination/dependency phrase.  This avoids over-splitting ordinary
        # Chinese commas while correctly handling forms such as "，并根据...".
        normalized = re.sub(
            r"[，,]\s*(?=(?:并(?:且|根据)?|以及|然后|接着|随后|之后|最后|最终|同时|分别|综合|根据|基于|依赖))",
            "\n",
            task,
            flags=re.IGNORECASE,
        )
        normalized = re.sub(
            r"(?:\band then\b|\bthen\b|然后|接着|随后|之后|最后|同时|分别|并且|以及)",
            "\n",
            normalized,
            flags=re.IGNORECASE,
        )

        parts = re.split(r"[\n；;。]+", normalized)
        clauses: list[str] = []
        for part in parts:
            clause = part.strip(" ,，:：")
            clause = re.sub(
                r"^(?:并(?:且)?(?:根据)?|再根据|根据|基于(?:上述|前面)?|综合)\s*",
                "",
                clause,
                flags=re.IGNORECASE,
            ).strip(" ,，:：")
            if len(clause) >= 4:
                clauses.append(clause)
        return clauses[:8]

    @staticmethod
    def _build_prompt(
        task: str,
        profile: TaskProfile,
        available: set[str],
        semantic: TaskSemanticIntent | None = None,
    ) -> str:
        catalog = sorted(available, key=str.casefold)
        return (
            "You are the AgentMesh semantic task planner. Produce JSON only.\n"
            "You decide WHAT work is needed; never select concrete agent IDs or names.\n"
            "Use only a capability from AVAILABLE_CAPABILITIES. Keep the plan minimal, "
            "bounded, acyclic, and dependency-aware. Independent steps should have no "
            "dependency so the runtime can execute them in parallel.\n"
            "Allowed condition values are null, 'always', or 'has_upstream_output'.\n"
            "Schema:\n"
            '{"goal":"...","requiresSynthesis":true,"steps":['
            '{"id":"short_id","objective":"...","capability":"...",'
            '"dependsOn":[],"optional":false,"condition":null,'
            '"knowledgeDependency":"NONE|OPTIONAL|REQUIRED","forbiddenActions":[]}]}\n'
            f"AVAILABLE_CAPABILITIES={json.dumps(catalog, ensure_ascii=False)}\n"
            f"BASELINE_PROFILE={profile.model_dump_json()}\n"
            f"SEMANTIC_CONSTRAINTS={(semantic.model_dump_json(by_alias=True) if semantic is not None else '{}')}\n"
            "Never weaken forbiddenActions. Knowledge dependency describes evidence requirements; it does not grant access.\n"
            "USER_GOAL_BEGIN\n"
            f"{task}\n"
            "USER_GOAL_END"
        )

    @staticmethod
    def _parse_plan(raw: str, *, source: str) -> ExecutionPlan:
        text = str(raw or "").strip()
        fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
        if fenced:
            text = fenced.group(1)
        else:
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                text = text[start : end + 1]
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise PlanValidationError("planner response must be a JSON object")
        payload["source"] = source
        return ExecutionPlan.model_validate(payload)
