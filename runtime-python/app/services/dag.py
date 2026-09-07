from app.schemas import (
    Assignment,
    DAGEdge,
    DAGNode,
    DynamicDAG,
)


def build_dag(
    assignments: list[Assignment],
    *,
    execution_mode: str = "parallel",
) -> DynamicDAG:
    """
    根据 Collaboration Planner 给出的 topology，
    将 Assignment 转换为真正的执行 DAG。

    当前支持：

    single:
        Task
          ↓
        Agent
          ↓
        Synthesis

    parallel:
             ┌→ Agent A ─┐
        Task ┤           ├→ Synthesis
             └→ Agent B ─┘

    sequential:
        Task
          ↓
        Agent A
          ↓
        Agent B
          ↓
        Synthesis

    注意：
    build_dag() 只负责构建执行图，
    不负责真正执行 Node。
    真正的依赖解析和执行由 DAGExecutor 完成。
    """

    if execution_mode not in {
        "single",
        "parallel",
        "sequential",
    }:
        raise ValueError(
            "unsupported DAG execution mode: "
            f"{execution_mode}"
        )

    # =====================================================
    # 1. Task Root Node
    # =====================================================

    nodes: list[DAGNode] = [
        DAGNode(
            id="task",
            label="Task",
            kind="task",
            status="completed",
        )
    ]

    edges: list[DAGEdge] = []

    agent_node_ids: list[str] = []

    # =====================================================
    # 2. Agent Nodes
    # =====================================================

    for index, assignment in enumerate(
        assignments,
        start=1,
    ):
        node_id = f"agent-{index}"

        agent_node_ids.append(
            node_id
        )

        nodes.append(
            DAGNode(
                id=node_id,
                label=(
                    f"{assignment.agent_name}\n"
                    f"[{assignment.capability}]"
                ),
                kind="agent",
                status="pending",
                capability=(
                    assignment.capability
                ),
                agentId=(
                    assignment.agent_id
                ),
                agentName=(
                    assignment.agent_name
                ),
            )
        )

    # =====================================================
    # 3. Synthesis Node
    # =====================================================

    nodes.append(
        DAGNode(
            id="synthesize",
            label="Synthesize",
            kind="synthesis",
            status="pending",
        )
    )

    # =====================================================
    # 4. Empty Assignment Protection
    # =====================================================

    if not agent_node_ids:
        edges.append(
            DAGEdge(
                source="task",
                target="synthesize",
            )
        )

        return DynamicDAG(
            nodes=nodes,
            edges=edges,
        )

    # =====================================================
    # 5. Single Topology
    #
    # Task → Agent → Synthesis
    # =====================================================

    if execution_mode == "single":
        if len(agent_node_ids) != 1:
            raise ValueError(
                "single topology requires "
                "exactly one agent node"
            )

        agent_node_id = (
            agent_node_ids[0]
        )

        edges.append(
            DAGEdge(
                source="task",
                target=agent_node_id,
            )
        )

        edges.append(
            DAGEdge(
                source=agent_node_id,
                target="synthesize",
            )
        )

    # =====================================================
    # 6. Parallel Topology
    #
    #          ┌→ A ─┐
    # Task ────┤     ├→ Synthesis
    #          └→ B ─┘
    # =====================================================

    elif execution_mode == "parallel":
        for node_id in agent_node_ids:
            edges.append(
                DAGEdge(
                    source="task",
                    target=node_id,
                )
            )

        for node_id in agent_node_ids:
            edges.append(
                DAGEdge(
                    source=node_id,
                    target="synthesize",
                )
            )

    # =====================================================
    # 7. Sequential Topology
    #
    # Task → A → B → C → Synthesis
    # =====================================================

    else:
        previous_node_id = "task"

        for node_id in agent_node_ids:
            edges.append(
                DAGEdge(
                    source=previous_node_id,
                    target=node_id,
                )
            )

            previous_node_id = (
                node_id
            )

        edges.append(
            DAGEdge(
                source=previous_node_id,
                target="synthesize",
            )
        )

    # =====================================================
    # 8. Final Dynamic DAG
    # =====================================================

    return DynamicDAG(
        nodes=nodes,
        edges=edges,
    )