from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


PlanCondition = Literal[
    "always",
    "has_upstream_output",
]


class PlanStep(BaseModel):
    """One semantic unit of work in an execution plan.

    The planner describes *what* must be done and which capability is required.
    It deliberately does not bind a concrete Agent; scheduling remains the
    responsibility of the existing AgentMesh Scheduler.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(min_length=1, max_length=64)
    objective: str = Field(min_length=1, max_length=4000)
    capability: str = Field(min_length=1, max_length=128)
    depends_on: list[str] = Field(default_factory=list, alias="dependsOn")
    optional: bool = False
    condition: PlanCondition | None = None


class ExecutionPlan(BaseModel):
    """Validated, model-independent task decomposition contract."""

    model_config = ConfigDict(populate_by_name=True)

    goal: str = Field(min_length=1, max_length=20000)
    steps: list[PlanStep] = Field(min_length=1)
    requires_synthesis: bool = Field(default=True, alias="requiresSynthesis")
    source: Literal[
        "semantic_model",
        "deterministic_fallback",
        "replan_model",
    ] = "semantic_model"
    reason: str = ""


@dataclass(slots=True)
class SemanticPlanningOutcome:
    plan: ExecutionPlan
    used_model: bool
    fallback_reason: str = ""
