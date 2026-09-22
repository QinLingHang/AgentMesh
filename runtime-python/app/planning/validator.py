from __future__ import annotations

import re
from collections import deque

from app.planning.contracts import ExecutionPlan, PlanStep


class PlanValidationError(ValueError):
    pass


class PlanValidator:
    """Normalizes untrusted planner output into a bounded executable plan.

    Planner output is treated as untrusted model output.  This validator keeps
    the graph bounded, removes invalid identifiers, validates dependency
    references/cycles, and prevents invented capabilities from bypassing the
    Scheduler capability boundary.
    """

    def __init__(self, *, max_steps: int = 8) -> None:
        self.max_steps = max(1, int(max_steps))

    def validate(
        self,
        plan: ExecutionPlan,
        *,
        available_capabilities: set[str],
        baseline_capabilities: list[str],
        completed_steps: dict[str, PlanStep] | None = None,
    ) -> ExecutionPlan:
        completed_steps = completed_steps or {}

        capability_map = {
            item.strip().casefold(): item.strip()
            for item in available_capabilities
            if item and item.strip()
        }
        has_general = "general" in capability_map or "*" in capability_map

        normalized_steps: list[PlanStep] = []
        id_map: dict[str, str] = {}
        normalized_ids: list[str] = []
        used_ids: set[str] = set()

        # First pass: normalize stable identifiers so dependencies can be
        # rewritten deterministically in the second pass. Duplicate identifiers
        # are rejected instead of silently renamed: a dependency that references
        # a duplicated planner ID is ambiguous and therefore unsafe to execute.
        for index, step in enumerate(plan.steps, start=1):
            raw_id = step.id.strip() or f"step_{index}"
            normalized_id = self._normalize_id(raw_id, index)
            if normalized_id in used_ids:
                raise PlanValidationError(
                    f"execution plan contains duplicate step id: {normalized_id}"
                )
            used_ids.add(normalized_id)
            normalized_ids.append(normalized_id)
            id_map[raw_id] = normalized_id
            id_map[step.id] = normalized_id

        if len(plan.steps) > self.max_steps:
            raise PlanValidationError(
                f"execution plan exceeds max steps: {len(plan.steps)} > {self.max_steps}"
            )

        # Preserve already completed steps exactly during replanning.  Replaying
        # them could duplicate remote or side-effecting work.
        preserved_completed: dict[str, PlanStep] = {
            key: value.model_copy(deep=True)
            for key, value in completed_steps.items()
        }

        for index, step in enumerate(plan.steps, start=1):
            normalized_id = normalized_ids[index - 1]

            if normalized_id in preserved_completed:
                normalized_steps.append(preserved_completed[normalized_id])
                continue

            capability = step.capability.strip()
            canonical = capability_map.get(capability.casefold())
            if canonical is None:
                if has_general:
                    canonical = capability_map.get("general") or capability_map.get("*") or "general"
                else:
                    raise PlanValidationError(
                        f"planner selected unsupported capability: {capability}"
                    )

            dependencies: list[str] = []
            for dependency in step.depends_on:
                mapped = id_map.get(dependency, dependency)
                mapped = self._normalize_id(mapped, 0)
                if mapped == normalized_id:
                    raise PlanValidationError(
                        f"plan step {normalized_id} cannot depend on itself"
                    )
                if mapped not in dependencies:
                    dependencies.append(mapped)

            normalized_steps.append(
                PlanStep(
                    id=normalized_id,
                    objective=step.objective.strip(),
                    capability=canonical,
                    dependsOn=dependencies,
                    optional=bool(step.optional),
                    condition=step.condition,
                    knowledgeDependency=step.knowledge_dependency,
                    forbiddenActions=list(dict.fromkeys(step.forbidden_actions)),
                )
            )

        # A replanner is not allowed to drop completed steps. Inject any omitted
        # completed step unchanged before validating downstream dependencies.
        normalized_ids = {step.id for step in normalized_steps}
        if preserved_completed:
            preserved_prefix = [
                step
                for step_id, step in preserved_completed.items()
                if step_id not in normalized_ids
            ]
            normalized_steps = preserved_prefix + normalized_steps

        # If a model accidentally omits a capability discovered by the trusted
        # profiler/A2A discovery path, append a bounded deterministic step rather
        # than silently losing required work.
        if len(normalized_steps) > self.max_steps:
            raise PlanValidationError(
                f"replanned execution plan exceeds max steps: {len(normalized_steps)} > {self.max_steps}"
            )

        present = {step.capability.casefold() for step in normalized_steps}
        for capability in baseline_capabilities:
            normalized_capability = capability.strip()
            if not normalized_capability or normalized_capability.casefold() in present:
                continue
            if len(normalized_steps) >= self.max_steps:
                raise PlanValidationError(
                    "planner omitted required capabilities and the bounded plan has no room"
                )
            step_id = self._unique_required_id(normalized_capability, {s.id for s in normalized_steps})
            canonical = capability_map.get(normalized_capability.casefold())
            if canonical is None and has_general:
                canonical = capability_map.get("general") or capability_map.get("*") or "general"
            if canonical is None:
                canonical = normalized_capability
            normalized_steps.append(
                PlanStep(
                    id=step_id,
                    objective=f"Handle the required capability '{normalized_capability}' for the user goal.",
                    capability=canonical,
                )
            )
            present.add(canonical.casefold())

        if normalized_steps and all(step.optional for step in normalized_steps):
            first = normalized_steps[0]
            normalized_steps[0] = first.model_copy(update={"optional": False})

        step_ids = {step.id for step in normalized_steps}
        for step in normalized_steps:
            missing = [item for item in step.depends_on if item not in step_ids]
            if missing:
                raise PlanValidationError(
                    f"plan step {step.id} references unknown dependencies: {missing}"
                )

        self._assert_acyclic(normalized_steps)

        return ExecutionPlan(
            goal=plan.goal.strip(),
            steps=normalized_steps,
            requiresSynthesis=bool(plan.requires_synthesis or len(normalized_steps) > 1),
            source=plan.source,
            reason=plan.reason,
        )

    @staticmethod
    def _normalize_id(value: str, index: int) -> str:
        value = re.sub(r"[^A-Za-z0-9_-]+", "_", str(value).strip()).strip("_")
        if not value:
            value = f"step_{index or 1}"
        return value[:64]

    @staticmethod
    def _unique_required_id(capability: str, used: set[str]) -> str:
        base = re.sub(r"[^A-Za-z0-9_-]+", "_", capability.strip()).strip("_") or "capability"
        candidate = f"required_{base}"[:64]
        suffix = 2
        while candidate in used:
            candidate = f"required_{base}_{suffix}"[:64]
            suffix += 1
        return candidate

    @staticmethod
    def _assert_acyclic(steps: list[PlanStep]) -> None:
        incoming = {step.id: set(step.depends_on) for step in steps}
        outgoing: dict[str, set[str]] = {step.id: set() for step in steps}
        for step in steps:
            for dep in step.depends_on:
                outgoing[dep].add(step.id)

        queue = deque(sorted(step_id for step_id, deps in incoming.items() if not deps))
        visited = 0
        while queue:
            current = queue.popleft()
            visited += 1
            for target in sorted(outgoing[current]):
                incoming[target].discard(current)
                if not incoming[target]:
                    queue.append(target)

        if visited != len(steps):
            cyclic = sorted(step_id for step_id, deps in incoming.items() if deps)
            raise PlanValidationError(f"execution plan contains a dependency cycle: {cyclic}")
