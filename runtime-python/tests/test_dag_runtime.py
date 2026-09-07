import asyncio

import pytest

from app.schemas import (
    DAGEdge,
    DAGNode,
    DynamicDAG,
)

from app.schemas import (
    AgentProfile,
    Assignment,
    RuntimeRequest,
)
from app.services import (
    RuntimeEngine,
    create_registry,
)
from app.services.dag import (
    build_dag,
)
from app.services.dag_executor import (
    DAGExecutor,
)


def assignments():
    return [
        Assignment(
            capability="business",
            agent_id=1,
            agent_name="BusinessAgent",
        ),
        Assignment(
            capability="data",
            agent_id=2,
            agent_name="DataAgent",
        ),
    ]


def test_parallel_dag_structure():
    dag = build_dag(
        assignments(),
        execution_mode="parallel",
    )

    edges = {
        (
            edge.source,
            edge.target,
        )
        for edge in dag.edges
    }

    assert (
        "task",
        "agent-1",
    ) in edges

    assert (
        "task",
        "agent-2",
    ) in edges

    assert (
        "agent-1",
        "synthesize",
    ) in edges

    assert (
        "agent-2",
        "synthesize",
    ) in edges


def test_sequential_dag_structure():
    dag = build_dag(
        assignments(),
        execution_mode="sequential",
    )

    edges = [
        (
            edge.source,
            edge.target,
        )
        for edge in dag.edges
    ]

    assert edges == [
        (
            "task",
            "agent-1",
        ),
        (
            "agent-1",
            "agent-2",
        ),
        (
            "agent-2",
            "synthesize",
        ),
    ]


@pytest.mark.asyncio
async def test_dag_executor_passes_upstream_result():
    dag = build_dag(
        assignments(),
        execution_mode="sequential",
    )

    executor = DAGExecutor()

    received_upstream = {}

    async def execute_node(
        node,
        upstream,
    ):
        await asyncio.sleep(
            0.01
        )

        received_upstream[
            node.id
        ] = dict(
            upstream
        )

        return (
            f"result-{node.id}"
        )

    result = await executor.execute(
        dag,
        execute_node,
    )

    assert (
        received_upstream[
            "agent-1"
        ]
        == {}
    )

    assert (
        received_upstream[
            "agent-2"
        ][
            "agent-1"
        ]
        == "result-agent-1"
    )

    assert result.outputs[
        "agent-1"
    ] == "result-agent-1"

    assert result.outputs[
        "agent-2"
    ] == "result-agent-2"


@pytest.mark.asyncio
async def test_runtime_sequential_dag():
    registry = await create_registry()

    try:
        engine = RuntimeEngine(
            registry
        )

        result = await engine.run(
            RuntimeRequest(
                user_id=1,
                request_id=(
                    "dag-runtime-test"
                ),
                task=(
                    "Analyze this order "
                    "and summarize the data."
                ),
                scheduler="fixed",
                executionMode=(
                    "sequential"
                ),
                agents=[
                    AgentProfile(
                        id=1,
                        name=(
                            "BusinessAgent"
                        ),
                        endpoint=(
                            "internal://business"
                        ),
                        protocol="internal",
                        capabilities=[
                            "business"
                        ],
                    ),
                    AgentProfile(
                        id=2,
                        name="DataAgent",
                        endpoint=(
                            "internal://data"
                        ),
                        protocol="internal",
                        capabilities=[
                            "data"
                        ],
                    ),
                ],
            )
        )

        assert len(
            result.dag.nodes
        ) == 4

        statuses = {
            node.id:
                node.status
            for node
            in result.dag.nodes
        }

        assert statuses[
            "task"
        ] == "completed"

        assert statuses[
            "agent-1"
        ] == "completed"

        assert statuses[
            "agent-2"
        ] == "completed"

        assert statuses[
            "synthesize"
        ] == "completed"

        edges = {
            (
                edge.source,
                edge.target,
            )
            for edge
            in result.dag.edges
        }

        assert (
            "agent-1",
            "agent-2",
        ) in edges

        assert any(
            item.kind
            == "dag_runtime"
            and item.title
            == "DAG Node Completed"
            for item
            in result.trace
        )
        

    finally:
        await registry.stop_all()

@pytest.mark.asyncio
async def test_single_agent_auto_bypasses_synthesis():
    registry = await create_registry()

    try:
        engine = RuntimeEngine(
            registry
        )

        result = await engine.run(
            RuntimeRequest(
                user_id=1,
                request_id=(
                    "single-agent-auto-"
                    "synthesis-test"
                ),
                task=(
                    "Explain an AI Agent."
                ),
                scheduler="fixed",
                synthesisMode="auto",
                agents=[
                    AgentProfile(
                        id=100,
                        name="GeneralAgent",
                        endpoint=(
                            "internal://general"
                        ),
                        protocol="internal",
                        capabilities=[
                            "general"
                        ],
                    )
                ],
            )
        )

        synthesis_node = next(
            node
            for node in result.dag.nodes
            if node.id
            == "synthesize"
        )

        assert (
            synthesis_node.status
            == "skipped"
        )

        assert any(
            item.kind
            == "synthesis"
            and item.title
            == (
                "Result Synthesizer "
                "Bypassed"
            )
            for item
            in result.trace
        )

        # Mock Agent 本身的结果应直接作为答案。
        assert (
            "[Mock Answer]"
            in result.answer
        )

    finally:
        await registry.stop_all()


@pytest.mark.asyncio
async def test_single_agent_always_runs_synthesis():
    registry = await create_registry()

    try:
        engine = RuntimeEngine(
            registry
        )

        result = await engine.run(
            RuntimeRequest(
                user_id=1,
                request_id=(
                    "single-agent-always-"
                    "synthesis-test"
                ),
                task=(
                    "Explain an AI Agent."
                ),
                scheduler="fixed",
                synthesisMode="always",
                agents=[
                    AgentProfile(
                        id=101,
                        name="GeneralAgent",
                        endpoint=(
                            "internal://general"
                        ),
                        protocol="internal",
                        capabilities=[
                            "general"
                        ],
                    )
                ],
            )
        )

        synthesis_node = next(
            node
            for node in result.dag.nodes
            if node.id
            == "synthesize"
        )

        assert (
            synthesis_node.status
            == "completed"
        )

        assert any(
            item.kind
            == "synthesis"
            and item.title
            == "Result Synthesizer"
            and item.status
            == "completed"
            for item
            in result.trace
        )

    finally:
        await registry.stop_all()


@pytest.mark.asyncio
async def test_multi_agent_auto_runs_synthesis():
    registry = await create_registry()

    try:
        engine = RuntimeEngine(
            registry
        )

        result = await engine.run(
            RuntimeRequest(
                user_id=1,
                request_id=(
                    "multi-agent-auto-"
                    "synthesis-test"
                ),
                task=(
                    "Analyze this order "
                    "and summarize the data."
                ),
                scheduler="fixed",
                executionMode="parallel",
                synthesisMode="auto",
                agents=[
                    AgentProfile(
                        id=201,
                        name="BusinessAgent",
                        endpoint=(
                            "internal://business"
                        ),
                        protocol="internal",
                        capabilities=[
                            "business"
                        ],
                    ),
                    AgentProfile(
                        id=202,
                        name="DataAgent",
                        endpoint=(
                            "internal://data"
                        ),
                        protocol="internal",
                        capabilities=[
                            "data"
                        ],
                    ),
                ],
            )
        )

        synthesis_node = next(
            node
            for node in result.dag.nodes
            if node.id
            == "synthesize"
        )

        assert (
            synthesis_node.status
            == "completed"
        )

        assert len(
            result.agent_feedback
        ) == 2


    finally:
        await registry.stop_all()
def test_single_dag_structure():
    dag = build_dag(
        [
            Assignment(
                capability="general",
                agent_id=1,
                agent_name="GeneralAgent",
            )
        ],
        execution_mode="single",
    )

    edges = [
        (
            edge.source,
            edge.target,
        )
        for edge in dag.edges
    ]

    assert edges == [
        (
            "task",
            "agent-1",
        ),
        (
            "agent-1",
            "synthesize",
        ),
    ]

@pytest.mark.asyncio
async def test_real_fan_out_fan_in():
    dag = DynamicDAG(
        nodes=[
            DAGNode(
                id="task",
                label="Task",
                kind="task",
                status="completed",
            ),
            DAGNode(
                id="agent-1",
                label="Agent A",
                kind="agent",
            ),
            DAGNode(
                id="agent-2",
                label="Agent B",
                kind="agent",
            ),
            DAGNode(
                id="agent-3",
                label="Agent C",
                kind="agent",
            ),
            DAGNode(
                id="synthesize",
                label="Synthesize",
                kind="synthesis",
            ),
        ],
        edges=[
            DAGEdge(
                source="task",
                target="agent-1",
            ),
            DAGEdge(
                source="task",
                target="agent-2",
            ),
            DAGEdge(
                source="agent-1",
                target="agent-3",
            ),
            DAGEdge(
                source="agent-2",
                target="agent-3",
            ),
            DAGEdge(
                source="agent-3",
                target="synthesize",
            ),
        ],
    )

    executor = DAGExecutor()

    seen = {}

    async def execute_node(
        node,
        upstream,
    ):
        seen[
            node.id
        ] = set(
            upstream.keys()
        )

        return (
            f"result-{node.id}"
        )

    result = await executor.execute(
        dag,
        execute_node,
    )

    assert seen[
        "agent-1"
    ] == set()

    assert seen[
        "agent-2"
    ] == set()

    assert seen[
        "agent-3"
    ] == {
        "agent-1",
        "agent-2",
    }

    assert (
        result.outputs[
            "agent-3"
        ]
        == "result-agent-3"
    )


@pytest.mark.asyncio
async def test_conditional_node_can_be_skipped():
    dag = DynamicDAG(
        nodes=[
            DAGNode(
                id="task",
                label="Task",
                kind="task",
                status="completed",
            ),
            DAGNode(
                id="agent-1",
                label="Agent A",
                kind="agent",
            ),
            DAGNode(
                id="agent-2",
                label="Conditional Agent",
                kind="agent",
                condition="never",
            ),
            DAGNode(
                id="agent-3",
                label="Agent C",
                kind="agent",
            ),
            DAGNode(
                id="synthesize",
                label="Synthesize",
                kind="synthesis",
            ),
        ],
        edges=[
            DAGEdge(
                source="task",
                target="agent-1",
            ),
            DAGEdge(
                source="agent-1",
                target="agent-2",
            ),
            DAGEdge(
                source="agent-2",
                target="agent-3",
            ),
            DAGEdge(
                source="agent-3",
                target="synthesize",
            ),
        ],
    )

    executor = DAGExecutor()

    executed = []

    async def execute_node(
        node,
        upstream,
    ):
        executed.append(
            node.id
        )

        return node.id

    def condition(
        node,
        upstream,
    ):
        return (
            node.condition
            != "never"
        )

    result = await executor.execute(
        dag,
        execute_node,
        condition_evaluator=(
            condition
        ),
    )

    assert (
        "agent-2"
        not in executed
    )

    assert (
        "agent-2"
        in result.skipped_nodes
    )

    assert (
        "agent-3"
        in executed
    )


@pytest.mark.asyncio
async def test_optional_failure_does_not_stop_dag():
    dag = DynamicDAG(
        nodes=[
            DAGNode(
                id="task",
                label="Task",
                kind="task",
                status="completed",
            ),
            DAGNode(
                id="agent-1",
                label="Optional Agent",
                kind="agent",
                optional=True,
            ),
            DAGNode(
                id="agent-2",
                label="Downstream Agent",
                kind="agent",
            ),
            DAGNode(
                id="synthesize",
                label="Synthesize",
                kind="synthesis",
            ),
        ],
        edges=[
            DAGEdge(
                source="task",
                target="agent-1",
            ),
            DAGEdge(
                source="agent-1",
                target="agent-2",
            ),
            DAGEdge(
                source="agent-2",
                target="synthesize",
            ),
        ],
    )

    executor = DAGExecutor()

    executed = []

    async def execute_node(
        node,
        upstream,
    ):
        executed.append(
            node.id
        )

        if (
            node.id
            == "agent-1"
        ):
            raise RuntimeError(
                "optional failure"
            )

        return (
            f"result-{node.id}"
        )

    result = await executor.execute(
        dag,
        execute_node,
    )

    assert (
        "agent-1"
        in result.skipped_nodes
    )

    assert (
        "agent-2"
        in executed
    )

    assert (
        result.outputs[
            "agent-2"
        ]
        == "result-agent-2"
    )