import pytest

from app.rag.agentic_retrieval import (
    AgenticRetrievalExecutor,
    EvidenceGrade,
)

from app.rag.runtime import (
    RetrievalDocument,
    RetrievalHit,
)


class FakeRetriever:

    def __init__(
        self,
        *,
        score: float = 0.8,
        empty_first_round: bool = False,
    ) -> None:

        self.score = score

        self.empty_first_round = (
            empty_first_round
        )

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

        if (
            self.empty_first_round
            and
            len(
                self.calls
            )
            <= 1
        ):

            return []

        return [
            RetrievalHit(
                document=(
                    RetrievalDocument(
                        id=(
                            f"doc-{query}"
                        ),
                        text=(
                            f"Knowledge for "
                            f"{query}"
                        ),
                        source="test",
                        metadata={},
                    )
                ),
                score=(
                    self.score
                ),
            )
        ]


class RetryGrader:

    def __init__(
        self,
    ) -> None:
        self.calls = 0

    async def grade(
        self,
        query,
        hits,
    ):

        self.calls += 1

        if self.calls == 1:

            return EvidenceGrade(
                relevance=0.2,
                coverage=0.2,
                confidence=0.9,
                sufficient=False,
                reason=(
                    "need more evidence"
                ),
            )

        return EvidenceGrade(
            relevance=0.9,
            coverage=0.9,
            confidence=0.95,
            sufficient=True,
            reason=(
                "enough evidence"
            ),
        )


@pytest.mark.asyncio
async def test_agentic_retrieval_stops_when_evidence_is_sufficient():

    retriever = (
        FakeRetriever(
            score=0.9
        )
    )

    executor = (
        AgenticRetrievalExecutor(
            retriever=(
                retriever
            )
        )
    )

    result = (
        await executor.retrieve(
            (
                "比较 MCP 和 A2A "
                "的架构区别"
            ),
            user_id=7,
            top_k=5,
            max_rounds=3,
            enable_query_rewrite=True,
            enable_multi_query=False,
            enable_decomposition=False,
        )
    )

    assert (
        result.sufficient
        is True
    )

    assert (
        result.stopped_reason
        ==
        "evidence_sufficient"
    )

    assert (
        len(
            result.rounds
        )
        == 1
    )

    assert (
        len(
            retriever.calls
        )
        == 1
    )

    assert (
        retriever.calls[
            0
        ][
            "filters"
        ]
        == {
            "userId": 7
        }
    )


@pytest.mark.asyncio
async def test_agentic_retrieval_retries_after_insufficient_evidence():

    retriever = (
        FakeRetriever(
            score=0.9
        )
    )

    grader = (
        RetryGrader()
    )

    executor = (
        AgenticRetrievalExecutor(
            retriever=(
                retriever
            ),
            grader=(
                grader
            ),
        )
    )

    result = (
        await executor.retrieve(
            (
                "分析 AgentMesh "
                "各模块之间的关系"
            ),
            user_id=1,
            top_k=5,
            max_rounds=3,
            enable_query_rewrite=True,
            enable_multi_query=False,
            enable_decomposition=False,
        )
    )

    assert (
        result.sufficient
        is True
    )

    assert (
        len(
            result.rounds
        )
        == 2
    )

    assert (
        grader.calls
        == 2
    )

    assert (
        len(
            retriever.calls
        )
        == 2
    )

    assert (
        "round 2"
        in retriever.calls[
            1
        ][
            "query"
        ]
    )
    assert (
    "need more evidence"
    in retriever.calls[
        1
    ][
        "query"
    ]
    )


@pytest.mark.asyncio
async def test_agentic_retrieval_multi_query_runs_in_parallel_contract():

    retriever = (
        FakeRetriever(
            score=0.8
        )
    )

    executor = (
        AgenticRetrievalExecutor(
            retriever=(
                retriever
            )
        )
    )

    result = (
        await executor.retrieve(
            (
                "AgentMesh RAG"
            ),
            user_id=3,
            top_k=8,
            max_rounds=1,
            enable_query_rewrite=False,
            enable_multi_query=True,
            enable_decomposition=False,
        )
    )

    assert (
        result.sufficient
        is True
    )

    queries = {
        call[
            "query"
        ]
        for call
        in retriever.calls
    }

    assert (
        "AgentMesh RAG"
        in queries
    )

    assert (
        "AgentMesh RAG architecture"
        in queries
    )

    assert (
        "AgentMesh RAG implementation"
        in queries
    )

    assert (
        len(
            queries
        )
        == 3
    )


@pytest.mark.asyncio
async def test_agentic_retrieval_deduplicates_documents():

    class DuplicateRetriever:

        async def retrieve(
            self,
            query: str,
            *,
            top_k: int = 5,
            filters=None,
        ):

            return [
                RetrievalHit(
                    document=(
                        RetrievalDocument(
                            id="same-doc",
                            text=(
                                "same document"
                            ),
                            source="test",
                            metadata={},
                        )
                    ),
                    score=(
                        0.7
                        if "architecture"
                        in query
                        else 0.9
                    ),
                )
            ]

    executor = (
        AgenticRetrievalExecutor(
            retriever=(
                DuplicateRetriever()
            )
        )
    )

    result = (
        await executor.retrieve(
            "AgentMesh RAG",
            user_id=1,
            top_k=5,
            max_rounds=1,
            enable_query_rewrite=False,
            enable_multi_query=True,
            enable_decomposition=False,
        )
    )

    assert (
        len(
            result.hits
        )
        == 1
    )

    assert (
        result.hits[
            0
        ].document.id
        == "same-doc"
    )

    assert (
        result.hits[
            0
        ].score
        == 0.9
    )


@pytest.mark.asyncio
async def test_agentic_retrieval_stops_at_max_rounds():

    class EmptyRetriever:

        def __init__(
            self,
        ) -> None:
            self.calls = 0

        async def retrieve(
            self,
            query,
            *,
            top_k=5,
            filters=None,
        ):

            self.calls += 1

            return []

    retriever = (
        EmptyRetriever()
    )

    executor = (
        AgenticRetrievalExecutor(
            retriever=(
                retriever
            )
        )
    )

    result = (
        await executor.retrieve(
            "找一个不存在的知识",
            user_id=1,
            top_k=5,
            max_rounds=3,
            enable_query_rewrite=True,
            enable_multi_query=False,
            enable_decomposition=False,
        )
    )

    assert (
        result.sufficient
        is False
    )

    assert (
        result.stopped_reason
        ==
        "max_rounds_reached"
    )

    assert (
        len(
            result.rounds
        )
        == 3
    )

    assert (
        retriever.calls
        == 3
    )