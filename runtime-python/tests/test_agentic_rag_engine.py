import json

import pytest

from app.rag.runtime import (
    RetrievalDocument,
    RetrievalHit,
)

from app.schemas import (
    AgentProfile,
    RuntimeRequest,
    TaskConstraints,
)

from app.services import (
    RuntimeEngine,
    create_registry,
)


class AgenticCountingRetriever:

    def __init__(
        self,
        *,
        return_hits: bool = True,
    ) -> None:

        self.return_hits = (
            return_hits
        )

        self.calls: list[
            dict
        ] = []

    async def retrieve(
        self,
        query: str,
        *,
        top_k: int = 5,
        filters: dict | None = None,
    ):

        self.calls.append(
            {
                "query":
                    query,

                "top_k":
                    top_k,

                "filters":
                    filters,
            }
        )

        if not self.return_hits:
            return []

        return [
            RetrievalHit(
                document=(
                    RetrievalDocument(
                        id=(
                            f"doc-{len(self.calls)}"
                        ),

                        text=(
                            "AgentMesh knowledge "
                            f"for query: {query}"
                        ),

                        source=(
                            "agentic-test"
                        ),

                        metadata={},
                    )
                ),

                score=0.90,
            )
        ]


def make_agent() -> AgentProfile:

    return AgentProfile(
        id=9001,

        name=(
            "AgenticRAGTestAgent"
        ),

        description=(
            "Agentic RAG "
            "integration test agent"
        ),

        endpoint=(
            "internal://agentic-rag"
        ),

        protocol="internal",

        capabilities=[
            "general",
            "knowledge",
            "document",
            "research",
            "data",
        ],

        provider="mock",

        qualityScore=0.9,

        avgLatencyMs=100,

        avgCost=0.001,

        successRate=0.99,

        failureRate=0.01,

        currentLoad=0.0,

        status="ACTIVE",
    )


def make_request(
    task: str,
) -> RuntimeRequest:

    return RuntimeRequest(
        user_id=1,

        request_id=(
            "agentic-rag-engine-test"
        ),

        task=task,

        scheduler="fixed",

        planner="heuristic",

        execution_mode=(
            "sequential"
        ),

        synthesis_mode="never",

        constraints=(
            TaskConstraints(
                maxLatencyMs=15000,
                maxCost=0.15,
                minQuality=0.8,
            )
        ),

        agents=[
            make_agent()
        ],
    )


@pytest.mark.asyncio
async def test_engine_executes_real_agentic_rag_path():

    registry = (
        await create_registry()
    )

    retriever = (
        AgenticCountingRetriever(
            return_hits=True
        )
    )

    engine = RuntimeEngine(
        registry,
        retriever=retriever,
    )

    try:

        result = (
            await engine.run(
                make_request(
                    (
                        "比较 AgentMesh 的 "
                        "MCP、A2A 和 Tool Runtime "
                        "之间的区别"
                    )
                )
            )
        )

        # =============================================
        # Router 必须选择 AGENTIC_RAG
        # =============================================

        route_events = [
            event
            for event
            in result.trace
            if (
                event.kind == "rag"
                and
                event.title
                == "RAG Route"
            )
        ]

        assert route_events

        route_detail = (
            json.loads(
                route_events[
                    0
                ].detail
            )
        )

        assert (
            route_detail[
                "mode"
            ]
            == "agentic_rag"
        )

        assert (
            route_detail[
                "retrieve"
            ]
            is True
        )

        assert (
            route_detail[
                "multiQuery"
            ]
            is True
        )

        assert (
            route_detail[
                "decomposition"
            ]
            is True
        )

        # =============================================
        # 必须真的产生多个 Retrieval Query
        #
        # 不能只是 Trace 上写 Agentic。
        # =============================================

        assert (
            len(
                retriever.calls
            )
            > 1
        )

        assert all(
            call[
                "filters"
            ]
            == {
                "userId": 1
            }

            for call
            in retriever.calls
        )

        # =============================================
        # Agentic Executor 必须完成
        # =============================================

        completed = [
            event
            for event
            in result.trace
            if (
                event.kind == "rag"
                and
                event.title
                == (
                    "Agentic RAG "
                    "Completed"
                )
            )
        ]

        assert completed

        detail = json.loads(
            completed[
                0
            ].detail
        )

        assert (
            detail[
                "rounds"
            ]
            >= 1
        )

        assert (
            detail[
                "sufficient"
            ]
            is True
        )

        assert (
            detail[
                "stoppedReason"
            ]
            == "evidence_sufficient"
        )

        assert (
            len(
                detail[
                    "roundDetails"
                ]
            )
            >= 1
        )

        # =============================================
        # 仍然应该有统一 Retrieval Completed
        # =============================================

        assert any(
            event.kind == "rag"
            and
            event.title
            == (
                "RAG Retrieval "
                "Completed"
            )

            for event
            in result.trace
        )

    finally:

        await engine.close()

        await registry.stop_all()


@pytest.mark.asyncio
async def test_engine_agentic_rag_retries_until_max_rounds():

    registry = (
        await create_registry()
    )

    retriever = (
        AgenticCountingRetriever(
            return_hits=False
        )
    )

    engine = RuntimeEngine(
        registry,
        retriever=retriever,
    )

    try:

        result = (
            await engine.run(
                make_request(
                    (
                        "比较并分析 AgentMesh "
                        "多个模块之间的依赖关系"
                    )
                )
            )
        )

        completed = [
            event
            for event
            in result.trace
            if (
                event.kind == "rag"
                and
                event.title
                == (
                    "Agentic RAG "
                    "Completed"
                )
            )
        ]

        assert completed

        detail = json.loads(
            completed[
                0
            ].detail
        )

        # Router 当前复杂任务预算是 3 rounds
        assert (
            detail[
                "rounds"
            ]
            == 3
        )

        assert (
            detail[
                "sufficient"
            ]
            is False
        )

        assert (
            detail[
                "stoppedReason"
            ]
            == "max_rounds_reached"
        )

        assert (
            detail[
                "finalGrade"
            ][
                "sufficient"
            ]
            is False
        )

        # 每一轮包含 MultiQuery / Decomposition，
        # 所以底层 Retriever 实际调用次数
        # 应明显大于 round 数。
        assert (
            len(
                retriever.calls
            )
            > 3
        )

    finally:

        await engine.close()

        await registry.stop_all()