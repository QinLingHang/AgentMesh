import asyncio

from collections.abc import (
    Awaitable,
    Callable,
)
from dataclasses import dataclass
from typing import Any

from app.schemas import (
    DAGNode,
    DynamicDAG,
)


DAGNodeExecutor = Callable[
    [
        DAGNode,
        dict[str, Any],
    ],
    Awaitable[Any],
]


DAGEventHandler = Callable[
    [
        dict[str, Any],
    ],
    None,
]


DAGConditionEvaluator = Callable[
    [
        DAGNode,
        dict[str, Any],
    ],
    bool,
]


class DAGExecutionError(
    RuntimeError
):
    def __init__(
        self,
        message: str,
        *,
        node_id: str | None = None,
        partial_result: "DAGExecutionResult | None" = None,
    ) -> None:
        super().__init__(message)
        self.node_id = node_id
        self.partial_result = partial_result


@dataclass(slots=True)
class DAGExecutionResult:
    outputs: dict[
        str,
        Any,
    ]

    completion_order: list[
        str
    ]

    skipped_nodes: list[
        str
    ]


class DAGExecutor:
    async def execute(
        self,
        dag: DynamicDAG,
        execute_node: DAGNodeExecutor,
        on_event: (
            DAGEventHandler | None
        ) = None,
        condition_evaluator: (
            DAGConditionEvaluator | None
        ) = None,
        initial_outputs: dict[str, Any] | None = None,
    ) -> DAGExecutionResult:
        # =================================================
        # Node index
        # =================================================

        nodes_by_id = {
            node.id: node
            for node in dag.nodes
        }

        # =================================================
        # Incoming dependencies
        #
        # incoming[C] = {A, B}
        #
        # 表示：
        #
        # A ─┐
        #    ├→ C
        # B ─┘
        # =================================================

        incoming: dict[
            str,
            set[str],
        ] = {
            node.id: set()
            for node in dag.nodes
        }

        for edge in dag.edges:
            if (
                edge.source
                not in nodes_by_id
            ):
                raise DAGExecutionError(
                    "DAG edge references "
                    "unknown source node: "
                    f"{edge.source}"
                )

            if (
                edge.target
                not in nodes_by_id
            ):
                raise DAGExecutionError(
                    "DAG edge references "
                    "unknown target node: "
                    f"{edge.target}"
                )

            incoming[
                edge.target
            ].add(
                edge.source
            )

        # =================================================
        # Runtime State
        # =================================================

        outputs: dict[
            str,
            Any,
        ] = dict(initial_outputs or {})

        completion_order: list[
            str
        ] = []

        skipped_nodes: list[
            str
        ] = []

        # ---------------------------------------------
        # resolved 和 completed 不完全一样。
        #
        # completed:
        #     真正执行成功。
        #
        # skipped:
        #     没执行，但已经不再阻塞下游。
        #
        # 所以 dependency resolution 应该依赖：
        #
        # resolved = completed + skipped
        # ---------------------------------------------

        resolved: set[str] = {
            node.id
            for node in dag.nodes
            if node.status
            in {
                "completed",
                "skipped",
            }
        }

        # Replanning may carry forward outputs from already completed semantic
        # steps. Only outputs whose node still exists are trusted as resolved.
        for node_id in list(outputs):
            if node_id not in nodes_by_id:
                outputs.pop(node_id, None)
                continue
            if nodes_by_id[node_id].kind == "agent":
                nodes_by_id[node_id].status = "completed"
                resolved.add(node_id)

        pending: set[str] = {
            node.id
            for node in dag.nodes
            if (
                node.kind == "agent"
                and node.status
                == "pending"
            )
        }

        # =================================================
        # Event Helper
        # =================================================

        def emit(
            title: str,
            status: str,
            node: DAGNode,
            **extra: Any,
        ) -> None:
            if on_event is None:
                return

            payload = {
                "kind":
                    "dag_runtime",

                "title":
                    title,

                "status":
                    status,

                "node_id":
                    node.id,

                "node_kind":
                    node.kind,

                "agent":
                    node.agent_name,

                "capability":
                    node.capability,

                "optional":
                    node.optional,

                "condition":
                    node.condition,
            }

            payload.update(
                extra
            )

            on_event(
                payload
            )

        # =================================================
        # Dependency Loop
        # =================================================

        while pending:
            # ---------------------------------------------
            # Ready Set
            #
            # 某节点所有前置依赖都 resolved 后，
            # 才允许进入 Ready Set。
            # ---------------------------------------------

            ready = [
                node_id
                for node_id in pending
                if incoming[
                    node_id
                ].issubset(
                    resolved
                )
            ]

            if not ready:
                unresolved = sorted(
                    pending
                )

                raise DAGExecutionError(
                    "DAG contains a cycle "
                    "or unresolved dependency: "
                    f"{unresolved}"
                )

            ready.sort()

            runnable: list[
                str
            ] = []

            # =================================================
            # Conditional Evaluation
            # =================================================

            for node_id in ready:
                node = nodes_by_id[
                    node_id
                ]

                upstream_outputs = {
                    dependency_id:
                        outputs[
                            dependency_id
                        ]

                    for dependency_id
                    in incoming[
                        node_id
                    ]

                    if dependency_id
                    in outputs
                }

                # -----------------------------------------
                # 普通 Node：
                # 没 condition，直接执行。
                # -----------------------------------------

                if node.condition is None:
                    runnable.append(
                        node_id
                    )

                    continue

                # -----------------------------------------
                # Conditional Node 必须由 Runtime
                # 提供 condition evaluator。
                # -----------------------------------------

                if condition_evaluator is None:
                    raise DAGExecutionError(
                        "conditional DAG node "
                        "requires condition evaluator: "
                        f"{node.id}"
                    )

                should_run = (
                    condition_evaluator(
                        node,
                        upstream_outputs,
                    )
                )

                # -----------------------------------------
                # Condition = False
                #
                # Node 不执行。
                # 但它已经 resolved，
                # 所以下游不会被永久阻塞。
                # -----------------------------------------

                if not should_run:
                    node.status = (
                        "skipped"
                    )

                    pending.remove(
                        node_id
                    )

                    resolved.add(
                        node_id
                    )

                    skipped_nodes.append(
                        node_id
                    )

                    emit(
                        "DAG Node Skipped",
                        "completed",
                        node,
                        reason=(
                            "condition evaluated "
                            "to false"
                        ),
                    )

                    continue

                runnable.append(
                    node_id
                )

            # ---------------------------------------------
            # 可能这一层全部都是 conditional skip。
            #
            # 这不是错误。
            # while 下一轮继续解析下游即可。
            # ---------------------------------------------

            if not runnable:
                continue

            # =================================================
            # Start Ready Nodes
            # =================================================

            for node_id in runnable:
                node = nodes_by_id[
                    node_id
                ]

                node.status = (
                    "running"
                )

                emit(
                    "DAG Node Started",
                    "running",
                    node,
                )

            # =================================================
            # Execute One Ready Batch
            #
            # 同一批 Ready Nodes 可以并行执行。
            # =================================================

            async def run_node(
                node_id: str,
            ):
                node = nodes_by_id[
                    node_id
                ]

                upstream_outputs = {
                    dependency_id:
                        outputs[
                            dependency_id
                        ]

                    for dependency_id
                    in incoming[
                        node_id
                    ]

                    if dependency_id
                    in outputs
                }

                return await execute_node(
                    node,
                    upstream_outputs,
                )

            results = await asyncio.gather(
                *(
                    run_node(
                        node_id
                    )
                    for node_id
                    in runnable
                ),
                return_exceptions=True,
            )

            first_error: (
                BaseException | None
            ) = None
            first_error_node_id: str | None = None

            # =================================================
            # Process Batch Results
            # =================================================

            for node_id, result in zip(
                runnable,
                results,
            ):
                node = nodes_by_id[
                    node_id
                ]

                pending.remove(
                    node_id
                )

                # =============================================
                # Node Failed
                # =============================================

                if isinstance(
                    result,
                    BaseException,
                ):
                    # -----------------------------------------
                    # Optional Node Failure
                    #
                    # 失败不终止整个 DAG。
                    #
                    # 将它视为 skipped / resolved，
                    # 下游继续执行。
                    # -----------------------------------------

                    if node.optional:
                        node.status = (
                            "skipped"
                        )

                        resolved.add(
                            node_id
                        )

                        skipped_nodes.append(
                            node_id
                        )

                        emit(
                            (
                                "DAG Optional "
                                "Node Failed"
                            ),
                            "error",
                            node,
                            error=(
                                type(result)
                                .__name__
                            ),
                            message=str(
                                result
                            ),
                        )

                        continue

                    # -----------------------------------------
                    # Mandatory Node Failure
                    #
                    # 当前 DAG Execution 终止。
                    #
                    # 注意：
                    # Agent 自身的 fallback 已经在
                    # RuntimeEngine.execute_assignment()
                    # 内尝试过。
                    #
                    # 到这里仍失败说明这个 DAG Node
                    # 已经无法完成。
                    # -----------------------------------------

                    node.status = (
                        "error"
                    )

                    emit(
                        "DAG Node Failed",
                        "error",
                        node,
                        error=(
                            type(result)
                            .__name__
                        ),
                        message=str(
                            result
                        ),
                    )

                    if first_error is None:
                        first_error = (
                            result
                        )
                        first_error_node_id = node_id

                    continue

                # =============================================
                # Node Completed
                # =============================================

                node.status = (
                    "completed"
                )

                outputs[
                    node_id
                ] = result

                resolved.add(
                    node_id
                )

                completion_order.append(
                    node_id
                )

                emit(
                    "DAG Node Completed",
                    "completed",
                    node,
                )

            # =================================================
            # Mandatory Failure Propagation
            # =================================================

            if first_error is not None:
                partial = DAGExecutionResult(
                    outputs=dict(outputs),
                    completion_order=list(completion_order),
                    skipped_nodes=list(skipped_nodes),
                )
                raise DAGExecutionError(
                    "DAG node execution failed",
                    node_id=first_error_node_id,
                    partial_result=partial,
                ) from first_error

        # =====================================================
        # Final Result
        # =====================================================

        return DAGExecutionResult(
            outputs=outputs,

            completion_order=(
                completion_order
            ),

            skipped_nodes=(
                skipped_nodes
            ),
        )