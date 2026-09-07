from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.agents.capability import (
    effective_capability_profile,
)
from app.schemas import (
    AgentProfile,
    Assignment,
    TaskConstraints,
    TaskProfile,
)


CollaborationTopology = Literal[
    "single",
    "parallel",
    "sequential",
]


@dataclass(slots=True)
class CollaborationPlan:
    topology: CollaborationTopology

    reason: str

    agent_count: int

    max_parallelism: int

    requires_synthesis: bool

    estimated_quality: float = 0.0

    estimated_reliability: float = 0.0

    estimated_latency_ms: int = 0

    estimated_cost: float = 0.0

    estimated_load: float = 0.0

    constraint_violation: float = 0.0

    utility_score: float = 0.0


class CollaborationPlanner:
    """
    Heuristic Collaboration Planner.

    这是 baseline。

    Scheduler:
        Who should execute?

    Planner:
        How should selected Agents collaborate?
    """

    def plan(
        self,
        *,
        assignments: list[Assignment],
        profile: TaskProfile,
        constraints: TaskConstraints,
        requested_mode: str = "auto",
        agents: list[AgentProfile] | None = None,
    ) -> CollaborationPlan:
        if not assignments:
            raise RuntimeError(
                "cannot create collaboration plan "
                "without assignments"
            )

        agent_count = len(
            assignments
        )

        # -----------------------------------------
        # Single Agent
        # -----------------------------------------

        if agent_count == 1:
            return CollaborationPlan(
                topology="single",
                reason=(
                    "only one agent assignment"
                ),
                agent_count=1,
                max_parallelism=1,
                requires_synthesis=False,
            )

        # -----------------------------------------
        # Explicit user policy
        # -----------------------------------------

        if requested_mode == "parallel":
            return CollaborationPlan(
                topology="parallel",
                reason=(
                    "parallel execution explicitly "
                    "requested"
                ),
                agent_count=agent_count,
                max_parallelism=agent_count,
                requires_synthesis=True,
            )

        if requested_mode == "sequential":
            return CollaborationPlan(
                topology="sequential",
                reason=(
                    "sequential execution explicitly "
                    "requested"
                ),
                agent_count=agent_count,
                max_parallelism=1,
                requires_synthesis=True,
            )

        if requested_mode != "auto":
            raise ValueError(
                "unsupported execution mode: "
                f"{requested_mode}"
            )

        # -----------------------------------------
        # High-risk task
        # -----------------------------------------

        if profile.risk_level == "high":
            return CollaborationPlan(
                topology="sequential",
                reason=(
                    "high-risk task prefers "
                    "controlled sequential execution"
                ),
                agent_count=agent_count,
                max_parallelism=1,
                requires_synthesis=True,
            )

        # -----------------------------------------
        # Parallelizable task
        # -----------------------------------------

        if profile.parallelizable:
            return CollaborationPlan(
                topology="parallel",
                reason=(
                    "task capabilities are "
                    "parallelizable"
                ),
                agent_count=agent_count,
                max_parallelism=agent_count,
                requires_synthesis=True,
            )

        return CollaborationPlan(
            topology="sequential",
            reason=(
                "task dependencies require "
                "sequential execution"
            ),
            agent_count=agent_count,
            max_parallelism=1,
            requires_synthesis=True,
        )


@dataclass(slots=True)
class TopologyEvaluation:
    topology: Literal[
        "parallel",
        "sequential",
    ]

    estimated_quality: float

    estimated_reliability: float

    estimated_latency_ms: int

    estimated_cost: float

    estimated_load: float

    constraint_violation: float

    utility_score: float


class MultiObjectiveCollaborationPlanner:
    """
    Multi-objective Collaboration Planner V1.

    当前优化目标：

    maximize:
        quality
        reliability

    minimize:
        latency
        cost
        load
        constraint violation

    当前只比较：
        parallel
        sequential

    后续可以继续扩展：
        hybrid
        hierarchical
        conditional
        dynamic fan-out/fan-in
    """

    def plan(
        self,
        *,
        assignments: list[Assignment],
        profile: TaskProfile,
        constraints: TaskConstraints,
        requested_mode: str = "auto",
        agents: list[AgentProfile] | None = None,
    ) -> CollaborationPlan:
        if not assignments:
            raise RuntimeError(
                "cannot create collaboration plan "
                "without assignments"
            )

        if agents is None:
            raise RuntimeError(
                "multi-objective planner "
                "requires agent profiles"
            )

        if len(assignments) == 1:
            evaluation = (
                self._evaluate_single(
                    assignments=assignments,
                    agents=agents,
                    constraints=constraints,
                )
            )

            return CollaborationPlan(
                topology="single",
                reason=(
                    "single-agent topology has "
                    "no collaboration alternative"
                ),
                agent_count=1,
                max_parallelism=1,
                requires_synthesis=False,
                estimated_quality=(
                    evaluation
                    .estimated_quality
                ),
                estimated_reliability=(
                    evaluation
                    .estimated_reliability
                ),
                estimated_latency_ms=(
                    evaluation
                    .estimated_latency_ms
                ),
                estimated_cost=(
                    evaluation
                    .estimated_cost
                ),
                estimated_load=(
                    evaluation
                    .estimated_load
                ),
                constraint_violation=(
                    evaluation
                    .constraint_violation
                ),
                utility_score=(
                    evaluation
                    .utility_score
                ),
            )

        if requested_mode in {
            "parallel",
            "sequential",
        }:
            evaluation = (
                self._evaluate_topology(
                    topology=requested_mode,
                    assignments=assignments,
                    agents=agents,
                    profile=profile,
                    constraints=constraints,
                )
            )

            return self._to_plan(
                evaluation,
                agent_count=len(
                    assignments
                ),
                reason=(
                    f"{requested_mode} topology "
                    "explicitly requested"
                ),
            )

        if requested_mode != "auto":
            raise ValueError(
                "unsupported execution mode: "
                f"{requested_mode}"
            )

        candidates = [
            self._evaluate_topology(
                topology="parallel",
                assignments=assignments,
                agents=agents,
                profile=profile,
                constraints=constraints,
            ),
            self._evaluate_topology(
                topology="sequential",
                assignments=assignments,
                agents=agents,
                profile=profile,
                constraints=constraints,
            ),
        ]

        best = max(
            candidates,
            key=lambda item:
                item.utility_score,
        )

        return self._to_plan(
            best,
            agent_count=len(
                assignments
            ),
            reason=(
                "selected by multi-objective "
                "collaboration utility"
            ),
        )

    def _selected_agents(
        self,
        assignments: list[Assignment],
        agents: list[AgentProfile],
    ) -> list[
        tuple[
            Assignment,
            AgentProfile,
        ]
    ]:
        agents_by_id = {
            agent.id:
                agent
            for agent in agents
        }

        selected: list[
            tuple[
                Assignment,
                AgentProfile,
            ]
        ] = []

        for assignment in assignments:
            agent = agents_by_id.get(
                assignment.agent_id
            )

            if agent is None:
                raise RuntimeError(
                    "assignment references "
                    "unknown agent: "
                    f"{assignment.agent_id}"
                )

            selected.append(
                (
                    assignment,
                    agent,
                )
            )

        return selected

    def _collect_metrics(
        self,
        *,
        assignments: list[Assignment],
        agents: list[AgentProfile],
    ) -> tuple[
        list[float],
        list[float],
        list[int],
        list[float],
        list[float],
    ]:
        qualities: list[
            float
        ] = []

        reliabilities: list[
            float
        ] = []

        latencies: list[
            int
        ] = []

        costs: list[
            float
        ] = []

        loads: list[
            float
        ] = []

        for (
            assignment,
            agent,
        ) in self._selected_agents(
            assignments,
            agents,
        ):
            metrics = (
                effective_capability_profile(
                    agent,
                    assignment.capability,
                )
            )

            qualities.append(
                min(
                    max(
                        metrics.quality_score,
                        0.0,
                    ),
                    1.0,
                )
            )

            reliabilities.append(
                min(
                    max(
                        metrics.success_rate,
                        0.0,
                    ),
                    1.0,
                )
            )

            latencies.append(
                max(
                    1,
                    metrics.avg_latency_ms,
                )
            )

            costs.append(
                max(
                    0.0,
                    metrics.avg_cost,
                )
            )

            loads.append(
                min(
                    max(
                        agent.current_load,
                        0.0,
                    ),
                    1.0,
                )
            )

        return (
            qualities,
            reliabilities,
            latencies,
            costs,
            loads,
        )

    def _evaluate_single(
        self,
        *,
        assignments: list[Assignment],
        agents: list[AgentProfile],
        constraints: TaskConstraints,
    ) -> TopologyEvaluation:
        (
            qualities,
            reliabilities,
            latencies,
            costs,
            loads,
        ) = self._collect_metrics(
            assignments=assignments,
            agents=agents,
        )

        quality = qualities[0]
        reliability = (
            reliabilities[0]
        )
        latency = latencies[0]
        cost = costs[0]
        load = loads[0]

        violation = (
            self._constraint_violation(
                quality=quality,
                latency_ms=latency,
                cost=cost,
                constraints=constraints,
            )
        )

        utility = (
            self._utility(
                quality=quality,
                reliability=reliability,
                latency_ms=latency,
                cost=cost,
                load=load,
                violation=violation,
                constraints=constraints,
                topology="sequential",
                profile=None,
            )
        )

        return TopologyEvaluation(
            topology="sequential",
            estimated_quality=quality,
            estimated_reliability=(
                reliability
            ),
            estimated_latency_ms=latency,
            estimated_cost=cost,
            estimated_load=load,
            constraint_violation=(
                violation
            ),
            utility_score=utility,
        )

    def _evaluate_topology(
        self,
        *,
        topology: Literal[
            "parallel",
            "sequential",
        ],
        assignments: list[Assignment],
        agents: list[AgentProfile],
        profile: TaskProfile,
        constraints: TaskConstraints,
    ) -> TopologyEvaluation:
        (
            qualities,
            reliabilities,
            latencies,
            costs,
            loads,
        ) = self._collect_metrics(
            assignments=assignments,
            agents=agents,
        )

        base_quality = (
            sum(
                qualities
            )
            / len(
                qualities
            )
        )

        # 所有参与 Agent 都成功，
        # 整条协作链才算可靠。
        reliability = 1.0

        for value in reliabilities:
            reliability *= (
                value
            )

        # -----------------------------------------
        # Parallel
        #
        # latency:
        #   近似由最慢 Agent 决定。
        #
        # Sequential
        #
        # latency:
        #   近似为各 Agent 延迟之和。
        # -----------------------------------------

        if topology == "parallel":
            latency = max(
                latencies
            )

            quality = (
                base_quality
            )

        else:
            latency = sum(
                latencies
            )

            # 顺序执行时，
            # 下游能够看到上游结果。
            #
            # 当前 V1 给一个小的 coordination bonus。
            # 后续这个值应由 Eval 数据学习，
            # 不是永久写死。
            quality = min(
                1.0,
                base_quality
                + 0.03,
            )

        cost = sum(
            costs
        )

        load = (
            sum(
                loads
            )
            / len(
                loads
            )
        )

        violation = (
            self._constraint_violation(
                quality=quality,
                latency_ms=latency,
                cost=cost,
                constraints=constraints,
            )
        )

        utility = (
            self._utility(
                quality=quality,
                reliability=reliability,
                latency_ms=latency,
                cost=cost,
                load=load,
                violation=violation,
                constraints=constraints,
                topology=topology,
                profile=profile,
            )
        )

        return TopologyEvaluation(
            topology=topology,
            estimated_quality=round(
                quality,
                6,
            ),
            estimated_reliability=round(
                reliability,
                6,
            ),
            estimated_latency_ms=(
                latency
            ),
            estimated_cost=round(
                cost,
                6,
            ),
            estimated_load=round(
                load,
                6,
            ),
            constraint_violation=round(
                violation,
                6,
            ),
            utility_score=round(
                utility,
                6,
            ),
        )

    def _constraint_violation(
        self,
        *,
        quality: float,
        latency_ms: int,
        cost: float,
        constraints: TaskConstraints,
    ) -> float:
        violation = 0.0

        if (
            quality
            < constraints.min_quality
        ):
            violation += (
                constraints.min_quality
                - quality
            ) / max(
                constraints.min_quality,
                1e-6,
            )

        if (
            latency_ms
            > constraints.max_latency_ms
        ):
            violation += (
                latency_ms
                - constraints.max_latency_ms
            ) / max(
                constraints.max_latency_ms,
                1,
            )

        if (
            cost
            > constraints.max_cost
        ):
            violation += (
                cost
                - constraints.max_cost
            ) / max(
                constraints.max_cost,
                1e-6,
            )

        return violation

    def _utility(
        self,
        *,
        quality: float,
        reliability: float,
        latency_ms: int,
        cost: float,
        load: float,
        violation: float,
        constraints: TaskConstraints,
        topology: str,
        profile: TaskProfile | None,
    ) -> float:
        latency_ratio = min(
            latency_ms
            / max(
                constraints.max_latency_ms,
                1,
            ),
            2.0,
        )

        cost_ratio = min(
            cost
            / max(
                constraints.max_cost,
                1e-6,
            ),
            2.0,
        )

        utility = (
            0.35 * quality
            + 0.25 * reliability
            - 0.15 * latency_ratio
            - 0.10 * cost_ratio
            - 0.05 * load
            - 0.20 * violation
        )

        # -----------------------------------------
        # Risk-aware topology penalty
        #
        # 高风险任务并行执行时，
        # 当前 V1 施加额外 penalty。
        #
        # 以后可以由风险模型 / Eval 数据替代。
        # -----------------------------------------

        if (
            profile is not None
            and profile.risk_level
            == "high"
            and topology
            == "parallel"
        ):
            utility -= 0.15

        return utility

    def _to_plan(
        self,
        evaluation: TopologyEvaluation,
        *,
        agent_count: int,
        reason: str,
    ) -> CollaborationPlan:
        topology = (
            evaluation.topology
        )

        return CollaborationPlan(
            topology=topology,
            reason=reason,
            agent_count=agent_count,
            max_parallelism=(
                agent_count
                if topology
                == "parallel"
                else 1
            ),
            requires_synthesis=(
                agent_count > 1
            ),
            estimated_quality=(
                evaluation
                .estimated_quality
            ),
            estimated_reliability=(
                evaluation
                .estimated_reliability
            ),
            estimated_latency_ms=(
                evaluation
                .estimated_latency_ms
            ),
            estimated_cost=(
                evaluation
                .estimated_cost
            ),
            estimated_load=(
                evaluation
                .estimated_load
            ),
            constraint_violation=(
                evaluation
                .constraint_violation
            ),
            utility_score=(
                evaluation
                .utility_score
            ),
        )