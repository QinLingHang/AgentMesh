from __future__ import annotations

from collections import defaultdict, deque

from app.planning import ExecutionPlan
from app.schemas import Assignment, DAGEdge, DAGNode, DynamicDAG


class PlanCompilationError(ValueError):
    pass


class PlanCompiler:
    """Compile a validated semantic ExecutionPlan into AgentMesh DynamicDAG."""

    def compile(
        self,
        plan: ExecutionPlan,
        assignments: list[Assignment],
    ) -> DynamicDAG:
        by_step = {
            assignment.step_id: assignment
            for assignment in assignments
            if assignment.step_id
        }
        if len(by_step) != len(plan.steps):
            raise PlanCompilationError(
                "semantic plan assignments do not cover every plan step"
            )

        nodes: list[DAGNode] = [
            DAGNode(id="task", label="Task", kind="task", status="completed")
        ]
        edges: list[DAGEdge] = []
        node_ids: dict[str, str] = {}

        for step in plan.steps:
            assignment = by_step.get(step.id)
            if assignment is None:
                raise PlanCompilationError(f"missing assignment for plan step: {step.id}")
            node_id = self.node_id(step.id)
            node_ids[step.id] = node_id
            nodes.append(
                DAGNode(
                    id=node_id,
                    label=(
                        f"{assignment.agent_name}\n"
                        f"[{assignment.capability}]\n"
                        f"{step.objective[:120]}"
                    ),
                    kind="agent",
                    capability=assignment.capability,
                    agentId=assignment.agent_id,
                    agentName=assignment.agent_name,
                    stepId=step.id,
                    objective=step.objective,
                    optional=step.optional,
                    condition=step.condition,
                )
            )

        for step in plan.steps:
            target = node_ids[step.id]
            if step.depends_on:
                for dependency in step.depends_on:
                    source = node_ids.get(dependency)
                    if source is None:
                        raise PlanCompilationError(
                            f"unknown dependency while compiling {step.id}: {dependency}"
                        )
                    edges.append(DAGEdge(source=source, target=target))
            else:
                edges.append(DAGEdge(source="task", target=target))

        nodes.append(
            DAGNode(id="synthesize", label="Synthesize", kind="synthesis", status="pending")
        )

        depended_on = {dependency for step in plan.steps for dependency in step.depends_on}
        leaves = [step.id for step in plan.steps if step.id not in depended_on]
        for step_id in leaves:
            edges.append(DAGEdge(source=node_ids[step_id], target="synthesize"))

        return DynamicDAG(nodes=nodes, edges=edges)

    @staticmethod
    def node_id(step_id: str) -> str:
        return f"step-{step_id}"

    @staticmethod
    def infer_topology(plan: ExecutionPlan) -> str:
        if len(plan.steps) <= 1:
            return "single"
        if all(not step.depends_on for step in plan.steps):
            return "parallel"

        previous: str | None = None
        chain = True
        for index, step in enumerate(plan.steps):
            if index == 0:
                chain = chain and not step.depends_on
            else:
                chain = chain and step.depends_on == [previous]
            previous = step.id
        if chain:
            return "sequential"
        return "hybrid"

    @staticmethod
    def max_parallelism(plan: ExecutionPlan) -> int:
        incoming = {step.id: set(step.depends_on) for step in plan.steps}
        outgoing: dict[str, set[str]] = defaultdict(set)
        for step in plan.steps:
            for dependency in step.depends_on:
                outgoing[dependency].add(step.id)

        ready = deque(sorted(step_id for step_id, deps in incoming.items() if not deps))
        resolved: set[str] = set()
        max_width = 0
        while ready:
            level = list(ready)
            ready.clear()
            max_width = max(max_width, len(level))
            for current in level:
                resolved.add(current)
                for target in outgoing[current]:
                    incoming[target].discard(current)
            for step_id, deps in incoming.items():
                if step_id not in resolved and not deps and step_id not in ready:
                    ready.append(step_id)
        return max(1, max_width)
