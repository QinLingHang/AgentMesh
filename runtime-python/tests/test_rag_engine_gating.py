import json

import pytest

from app.schemas import (
    AgentProfile,
    RuntimeRequest,
    TaskConstraints,
)

from app.services import (
    RuntimeEngine,
    create_registry,
)


class CountingRetriever:
    """
    Test Retriever.

    不关心检索质量，
    只记录 Engine 到底有没有调用 retrieve()。
    """

    def __init__(
        self,
    ) -> None:
        self.calls: list[
            dict
        ] = []

    async def retrieve(
        self,
        query: str,
        *,
        top_k: int = 5,
        filters: dict
        | None = None,
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

        return []


def make_agent(
    *,
    agent_id: int,
    name: str,
    capabilities: list[
        str
    ],
) -> AgentProfile:

    return AgentProfile(
        id=agent_id,

        name=name,

        description=(
            "RAG gating test agent"
        ),

        endpoint=(
            "internal://general"
        ),

        protocol="internal",

        capabilities=(
            capabilities
        ),

        provider="mock",

        qualityScore=0.9,

        avgLatencyMs=100,

        avgCost=0.001,

        successRate=0.99,

        failureRate=0.01,

        currentLoad=0.0,

        status="ACTIVE",
    )


@pytest.mark.asyncio
async def test_engine_no_rag_really_skips_retriever():
    registry = (
        await create_registry()
    )

    retriever = (
        CountingRetriever()
    )

    engine = RuntimeEngine(
        registry,
        retriever=retriever,
    )

    try:

        req = RuntimeRequest(
            user_id=1,

            request_id=(
                "rag-gating-business"
            ),

            task=(
                "Please query this order "
                "current processing status."
            ),

            scheduler="fixed",

            planner="heuristic",

            execution_mode=(
                "sequential"
            ),

            synthesis_mode="never",

            constraints=(
                TaskConstraints(
                    maxLatencyMs=8000,
                    maxCost=0.15,
                    minQuality=0.8,
                )
            ),

            agents=[
                make_agent(
                    agent_id=1,
                    name=(
                        "BusinessAgent"
                    ),
                    capabilities=[
                        "business",
                        "general",
                    ],
                )
            ],
        )

        result = (
            await engine.run(
                req
            )
        )

        # =============================================
        # Core Assertion
        #
        # NO_RAG 的含义不是：
        #
        # retrieve → ignore
        #
        # 而是：
        #
        # retrieve 根本没调用。
        # =============================================

        assert (
            len(
                retriever.calls
            )
            == 0
        )

        route_events = [
            item
            for item
            in result.trace
            if (
                item.kind
                == "rag"
                and
                item.title
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
            == "no_rag"
        )

        assert (
            route_detail[
                "retrieve"
            ]
            is False
        )

        assert any(
            item.kind
            == "rag"
            and
            item.title
            == (
                "RAG Retrieval "
                "Skipped"
            )

            for item
            in result.trace
        )

        assert not any(
            item.kind
            == "rag"
            and
            item.title
            == (
                "RAG Retrieval "
                "Started"
            )

            for item
            in result.trace
        )

    finally:

        await engine.close()

        await registry.stop_all()


@pytest.mark.asyncio
async def test_engine_fast_rag_calls_retriever():
    registry = (
        await create_registry()
    )

    retriever = (
        CountingRetriever()
    )

    engine = RuntimeEngine(
        registry,
        retriever=retriever,
    )

    try:

        req = RuntimeRequest(
            user_id=1,

            request_id=(
                "rag-gating-knowledge"
            ),

            ragPolicy={"mode": "ON", "scopes": ["PROJECT"]},
            effectiveRagPolicy={
                "mode": "ON", "allowedScopes": ["PROJECT"],
                "allowedKnowledgeBaseIds": [9],
            },
            knowledgeCatalog=[{
                "knowledgeBaseId": 9,
                "name": "AgentMesh Project BYOK MCP A2A Tool Runtime Failure Backoff",
                "scope": "PROJECT", "accessible": True,
            }],

            task=(
                "AgentMesh 的 MCP "
                "Failure Backoff 是什么？"
            ),

            scheduler="fixed",

            planner="heuristic",

            execution_mode=(
                "sequential"
            ),

            synthesis_mode="never",

            constraints=(
                TaskConstraints(
                    maxLatencyMs=8000,
                    maxCost=0.15,
                    minQuality=0.8,
                )
            ),

            agents=[
                make_agent(
                    agent_id=1,
                    name=(
                        "GeneralAgent"
                    ),
                    capabilities=[
                        "general",
                    ],
                )
            ],
        )

        result = (
            await engine.run(
                req
            )
        )

        assert (
            len(
                retriever.calls
            )
            == 1
        )

        call = (
            retriever.calls[
                0
            ]
        )

        assert (
            call["query"]
            == req.task
        )

        assert (
            call["filters"]
            == {
                "userId": 1
            }
        )

        route_events = [
            item
            for item
            in result.trace
            if (
                item.kind
                == "rag"
                and
                item.title
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
            == "fast_rag"
        )

        assert (
            route_detail[
                "retrieve"
            ]
            is True
        )

        assert any(
            item.kind
            == "rag"
            and
            item.title
            == (
                "RAG Retrieval "
                "Started"
            )

            for item
            in result.trace
        )

        assert any(
            item.kind
            == "rag"
            and
            item.title
            == (
                "RAG Retrieval "
                "Completed"
            )

            for item
            in result.trace
        )

    finally:

        await engine.close()

        await registry.stop_all()