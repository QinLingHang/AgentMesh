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


class RecoveryDecompositionTransformer:
    def __init__(
        self,
        *,
        fail_decomposition: bool = False,
        return_distinct_facets: bool = True,
    ) -> None:
        self.fail_decomposition = fail_decomposition
        self.return_distinct_facets = return_distinct_facets
        self.decompose_calls: list[str] = []

    async def rewrite(
        self,
        query: str,
        *,
        round_index: int,
        previous_query: str | None = None,
        feedback: str | None = None,
    ) -> str:
        return query

    async def multi_query(self, query: str) -> list[str]:
        return []

    async def decompose(self, query: str) -> list[str]:
        self.decompose_calls.append(query)

        if self.fail_decomposition:
            raise RuntimeError("synthetic decomposition failure")

        if not self.return_distinct_facets:
            return [query]

        return [
            "workflow approval threshold rule",
            "workflow retry timing rule",
        ]


class ThreeRoundGrader:
    def __init__(self) -> None:
        self.calls = 0

    async def grade(self, query, hits):
        self.calls += 1
        sufficient = self.calls >= 3
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
    assert (
        result.rounds[1].recovery_decomposition_attempted
        is True
    )
    assert (
        result.rounds[1].recovery_decomposition_query_count
        == 0
    )
    assert (
        result.rounds[1].recovery_decomposition_status
        == "no_distinct_queries"
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



@pytest.mark.asyncio
async def test_evidence_retry_decomposition_adds_distinct_facet_queries_once():
    retriever = WindowRetriever()
    grader = TwoRoundGrader()
    transformer = RecoveryDecompositionTransformer()

    executor = AgenticRetrievalExecutor(
        retriever=retriever,
        transformer=transformer,
        grader=grader,
    )

    original_query = (
        "For workflow ME-01, give both the rule about "
        "approval threshold and the rule about retry timing."
    )

    result = await executor.retrieve(
        original_query,
        user_id=17,
        top_k=5,
        max_rounds=2,
        enable_query_rewrite=False,
        enable_multi_query=False,
        enable_decomposition=False,
    )

    assert transformer.decompose_calls == [original_query]
    assert [call["top_k"] for call in retriever.calls] == [5, 10, 10, 10]

    round0, round1 = result.rounds
    assert round0.recovery_decomposition_attempted is False
    assert round0.recovery_decomposition_query_count == 0

    assert round1.recovery_decomposition_attempted is True
    assert round1.recovery_decomposition_query_count == 2
    assert round1.recovery_decomposition_status == "applied"
    assert round1.queries == [
        original_query,
        "workflow approval threshold rule",
        "workflow retry timing rule",
    ]
    assert round1.candidate_budget_reason == "decomposition+evidence_retry"

    assert grader.hit_counts == [5, 5]
    assert len(result.hits) == 5
    assert round1.final_top_k == 5
    assert round1.candidate_pool_limit == 20


@pytest.mark.asyncio
async def test_evidence_retry_decomposition_uses_original_not_rewritten_query():
    retriever = WindowRetriever()
    grader = TwoRoundGrader()

    class RewritingTransformer(RecoveryDecompositionTransformer):
        async def rewrite(
            self,
            query: str,
            *,
            round_index: int,
            previous_query: str | None = None,
            feedback: str | None = None,
        ) -> str:
            return f"rewritten round {round_index + 1}"

    transformer = RewritingTransformer()

    executor = AgenticRetrievalExecutor(
        retriever=retriever,
        transformer=transformer,
        grader=grader,
    )

    original_query = "approval threshold plus retry timing"

    await executor.retrieve(
        original_query,
        user_id=19,
        top_k=5,
        max_rounds=2,
        enable_query_rewrite=True,
        enable_multi_query=False,
        enable_decomposition=False,
    )

    assert transformer.decompose_calls == [original_query]


@pytest.mark.asyncio
async def test_evidence_retry_decomposition_failure_isolated_to_existing_path():
    retriever = WindowRetriever()
    grader = TwoRoundGrader()
    transformer = RecoveryDecompositionTransformer(
        fail_decomposition=True,
    )

    executor = AgenticRetrievalExecutor(
        retriever=retriever,
        transformer=transformer,
        grader=grader,
    )

    result = await executor.retrieve(
        "approval threshold and retry timing",
        user_id=23,
        top_k=5,
        max_rounds=2,
        enable_query_rewrite=False,
        enable_multi_query=False,
        enable_decomposition=False,
    )

    assert len(result.rounds) == 2
    assert len(result.hits) == 5
    assert [call["top_k"] for call in retriever.calls] == [5, 10]

    round1 = result.rounds[1]
    assert round1.recovery_decomposition_attempted is True
    assert round1.recovery_decomposition_query_count == 0
    assert round1.recovery_decomposition_status == "failed"
    assert round1.candidate_budget_reason == "evidence_retry"


@pytest.mark.asyncio
async def test_evidence_retry_decomposition_is_attempted_at_most_once():
    retriever = WindowRetriever()
    grader = ThreeRoundGrader()
    transformer = RecoveryDecompositionTransformer()

    executor = AgenticRetrievalExecutor(
        retriever=retriever,
        transformer=transformer,
        grader=grader,
    )

    original_query = "approval threshold plus retry timing"

    result = await executor.retrieve(
        original_query,
        user_id=29,
        top_k=5,
        max_rounds=3,
        enable_query_rewrite=False,
        enable_multi_query=False,
        enable_decomposition=False,
    )

    assert transformer.decompose_calls == [original_query]
    assert len(result.rounds) == 3
    assert result.rounds[1].recovery_decomposition_status == "applied"
    assert result.rounds[2].recovery_decomposition_attempted is False


@pytest.mark.asyncio
async def test_explicit_decomposition_does_not_double_trigger_recovery():
    retriever = WindowRetriever()
    grader = TwoRoundGrader()
    transformer = RecoveryDecompositionTransformer()

    executor = AgenticRetrievalExecutor(
        retriever=retriever,
        transformer=transformer,
        grader=grader,
    )

    result = await executor.retrieve(
        "approval threshold and retry timing",
        user_id=31,
        top_k=5,
        max_rounds=2,
        enable_query_rewrite=False,
        enable_multi_query=False,
        enable_decomposition=True,
    )

    assert len(transformer.decompose_calls) == 2
    assert all(
        round_item.recovery_decomposition_attempted is False
        for round_item in result.rounds
    )
    assert result.rounds[0].candidate_budget_reason == "decomposition"
    assert (
        result.rounds[1].candidate_budget_reason
        == "decomposition+evidence_retry"
    )
    assert len(result.hits) == 5


@pytest.mark.asyncio
async def test_evidence_retry_decomposition_can_be_disabled_for_control_runs():
    retriever = WindowRetriever()
    grader = TwoRoundGrader()
    transformer = RecoveryDecompositionTransformer()

    executor = AgenticRetrievalExecutor(
        retriever=retriever,
        transformer=transformer,
        grader=grader,
        enable_evidence_retry_decomposition=False,
    )

    result = await executor.retrieve(
        "approval threshold and retry timing",
        user_id=37,
        top_k=5,
        max_rounds=2,
        enable_query_rewrite=False,
        enable_multi_query=False,
        enable_decomposition=False,
    )

    assert transformer.decompose_calls == []
    assert [call["top_k"] for call in retriever.calls] == [5, 10]
    assert result.rounds[1].candidate_budget_reason == "evidence_retry"
    assert result.rounds[1].recovery_decomposition_attempted is False
