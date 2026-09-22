"""Deterministic, fail-closed step-level knowledge evidence boundary.

This is deliberately independent of the Planner model and of tool metadata:
a missing REQUIRED source blocks its step and the transitive dependants.  It
never grants a missing source or silently converts a blocked step to OPTIONAL.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.planning.contracts import ExecutionPlan


@dataclass(frozen=True)
class KnowledgeStepGate:
    blocked: dict[str, str]
    runnable: tuple[str, ...]

    @property
    def partial(self) -> bool:
        return bool(self.blocked and self.runnable)


def partition_knowledge_steps(
    plan: ExecutionPlan,
    *,
    insufficient_required: set[str],
    global_requirement_unresolved: bool = False,
) -> KnowledgeStepGate:
    """Propagate blocked REQUIRED steps through dependencies, never through siblings.

    An unscoped request-level REQUIRED obligation cannot safely be associated
    with particular steps; without an explicit per-step mapping, stop all.
    """
    known = {step.id for step in plan.steps}
    seeds = set(insufficient_required)
    if not seeds.issubset(known):
        raise ValueError("unknown REQUIRED step in evidence gate")
    if any(step.id in seeds and step.knowledge_dependency != "REQUIRED" for step in plan.steps):
        raise ValueError("evidence gate may only directly block REQUIRED steps")

    blocked = {step_id: "required_evidence_unavailable" for step_id in seeds}
    if global_requirement_unresolved and not any(
        step.knowledge_dependency == "REQUIRED" for step in plan.steps
    ):
        blocked = {step.id: "unscoped_required_evidence_unavailable" for step in plan.steps}

    changed = True
    while changed:
        changed = False
        for step in plan.steps:
            if step.id not in blocked and any(dep in blocked for dep in step.depends_on):
                blocked[step.id] = "upstream_required_evidence_unavailable"
                changed = True
    return KnowledgeStepGate(
        blocked=blocked,
        runnable=tuple(step.id for step in plan.steps if step.id not in blocked),
    )
