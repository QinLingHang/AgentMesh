import pytest

from app.rag.agentic_retrieval import (
    AgenticRetrievalExecutor,
    EvidenceGrade,
)
from app.rag.runtime import (
    RetrievalDocument,
    RetrievalHit,
)


class WindowRetriever:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def retrieve(
        self,
        query: str,
        *,
        top_k: int = 5,
        filters=None,
    ):
        self.calls.append(
            {
                "query": query,
                "top_k": top_k,
                "filters": filters,
            }
        )

        slug = (
            query.lower()
            .replace(" ", "-")
            .replace(":", "-")
        )

        return [
            RetrievalHit(
                document=RetrievalDocument(
                    id=f"{slug}-{index}",
                    text=f"evidence {index} for {query}",
                    source="test",
                    metadata={},
                ),
                score=max(0.01, 1.0 - index * 0.01),
            )
            for index in range(top_k)
        ]


class RecordingGrader:
    def __init__(self, *, sufficient=True) -> None:
        self.sufficient = sufficient
        self.hit_counts: list[int] = []

    async def grade(self, query, hits):
        self.hit_counts.append(len(hits))
        return EvidenceGrade(
            relevance=0.9 if hits else 0.0,
            coverage=1.0 if hits else 0.0,
            confidence=0.95,
            sufficient=bool(hits) and self.sufficient,
            reason=(
                "enough evidence"
                if self.sufficient
                else "need more evidence"
            ),
        )


class TwoRoundGrader:
    def __init__(self) -> None:
        self.calls = 0
        self.hit_counts: list[int] = []

    async def grade(self, query, hits):
        self.calls += 1
        self.hit_counts.append(len(hits))
        sufficient = self.calls >= 2
        return EvidenceGrade(
            relevance=0.9,
            coverage=0.9,
            confidence=0.95,
            sufficient=sufficient,
            reason=(
                "enough evidence"
                if sufficient
                else "need more evidence"
            ),
        )


@pytest.mark.asyncio
async def test_multi_query_retrieves_wide_but_returns_and_grades_narrow():
    retriever = WindowRetriever()
    grader = RecordingGrader()
    executor = AgenticRetrievalExecutor(
        retriever=retriever,
        grader=grader,
    )

    result = await executor.retrieve(
        "AgentMesh RAG",
        user_id=7,
        top_k=5,
        max_rounds=1,
        enable_query_rewrite=False,
        enable_multi_query=True,
        enable_decomposition=False,
    )

    assert len(retriever.calls) == 3
    assert {
        call["top_k"]
        for call in retriever.calls
    } == {8}
    assert all(
        call["filters"] == {"userId": 7}
        for call in retriever.calls
    )

    # Retrieve wide, but the evidence grader and result stay at final Top-K.
    assert grader.hit_counts == [5]
    assert len(result.hits) == 5

    round0 = result.rounds[0]
    assert round0.retrieval_top_k == 8
    assert round0.candidate_pool_count == 20
    assert round0.candidate_pool_limit == 20
    assert round0.final_top_k == 5
    assert round0.candidate_budget_reason == "multi_query"


@pytest.mark.asyncio
async def test_decomposition_uses_two_x_window_with_fixed_final_top_k():
    retriever = WindowRetriever()
    grader = RecordingGrader()
    executor = AgenticRetrievalExecutor(
        retriever=retriever,
        grader=grader,
    )

    result = await executor.retrieve(
        "approval threshold and retry timing",
        user_id=9,
        top_k=5,
        max_rounds=1,
        enable_query_rewrite=False,
        enable_multi_query=False,
        enable_decomposition=True,
    )

    assert len(retriever.calls) >= 2
    assert {
        call["top_k"]
        for call in retriever.calls
    } == {10}
    assert len(result.hits) == 5
    assert grader.hit_counts == [5]
    assert (
        result.rounds[0].candidate_budget_reason
        == "decomposition"
    )


@pytest.mark.asyncio
async def test_second_round_expands_after_insufficient_evidence():
    retriever = WindowRetriever()
    grader = TwoRoundGrader()
    executor = AgenticRetrievalExecutor(
        retriever=retriever,
        grader=grader,
    )

    result = await executor.retrieve(
        "AgentMesh recovery behavior",
        user_id=11,
        top_k=5,
        max_rounds=2,
        enable_query_rewrite=True,
        enable_multi_query=False,
        enable_decomposition=False,
    )

    assert [
        call["top_k"]
        for call in retriever.calls
    ] == [5, 10]
    assert grader.hit_counts == [5, 5]
    assert len(result.hits) == 5
    assert len(result.rounds) == 2
    assert (
        result.rounds[0].candidate_budget_reason
        == "base"
    )
    assert (
        result.rounds[1].candidate_budget_reason
        == "evidence_retry"
    )
    assert result.rounds[1].candidate_pool_count <= 20


@pytest.mark.asyncio
async def test_simple_first_round_keeps_previous_budget_behavior():
    retriever = WindowRetriever()
    grader = RecordingGrader()
    executor = AgenticRetrievalExecutor(
        retriever=retriever,
        grader=grader,
    )

    result = await executor.retrieve(
        "simple knowledge question",
        user_id=13,
        top_k=5,
        max_rounds=1,
        enable_query_rewrite=False,
        enable_multi_query=False,
        enable_decomposition=False,
    )

    assert len(retriever.calls) == 1
    assert retriever.calls[0]["top_k"] == 5
    assert len(result.hits) == 5
    assert result.rounds[0].candidate_pool_count == 5
    assert result.rounds[0].candidate_budget_reason == "base"
