from __future__ import annotations

import inspect

import pytest

from app.rag.agentic_retrieval import (
    AgenticRetrievalExecutor,
)

from app.rag.model_intelligence import (
    ModelBackedEvidenceGrader,
    ModelBackedQueryTransformer,
)

from app.rag.runtime import (
    RetrievalDocument,
    RetrievalHit,
)


class FakeRetriever:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def retrieve(
        self,
        query: str,
        *,
        top_k: int = 5,
        filters: dict | None = None,
    ):
        self.calls.append(
            {
                "query": query,
                "top_k": top_k,
                "filters": filters,
            }
        )

        return [
            RetrievalHit(
                document=RetrievalDocument(
                    id="doc-runtime-contract",
                    text=(
                        "AgentMesh Agentic RAG uses "
                        "multi-round retrieval and evidence grading."
                    ),
                    source="unit-test",
                    metadata={},
                ),
                score=0.91,
            )
        ]


class FakeModel:
    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.responses = [
            """
            {
              "query":
                "AgentMesh Agentic RAG retrieval architecture"
            }
            """,
            """
            {
              "relevance": 0.96,
              "coverage": 0.93,
              "confidence": 0.95,
              "sufficient": true,
              "reason":
                "The evidence directly covers the retrieval architecture."
            }
            """,
        ]

    async def generate(
        self,
        prompt: str,
        on_event=None,
    ) -> str:
        self.prompts.append(prompt)

        if not self.responses:
            raise AssertionError(
                "FakeModel received more calls than expected"
            )

        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_agentic_round_exposes_runtime_engine_trace_contract():
    """
    RuntimeEngine 在 Agentic RAG trace 中会读取：

        item.round_index
        item.queries
        item.hit_count
        item.grade

    这个测试锁住 Round DTO 与 Engine 的契约。
    """

    executor = AgenticRetrievalExecutor(
        retriever=FakeRetriever(),
    )

    result = await executor.retrieve(
        "AgentMesh RAG",
        user_id=7,
        top_k=5,
        max_rounds=1,
        enable_query_rewrite=False,
        enable_multi_query=False,
        enable_decomposition=False,
    )

    assert len(result.rounds) == 1

    round_item = result.rounds[0]

    assert round_item.round_index == 0
    assert round_item.queries == [
        "AgentMesh RAG"
    ]
    assert round_item.hit_count == 1
    assert round_item.hit_count == len(
        round_item.hits
    )

    assert (
        result.final_grade
        is result.grade
    )


@pytest.mark.asyncio
async def test_model_backed_agentic_components_work_as_one_executor():
    """
    模拟 RuntimeEngine 当前真实 wiring：

        ModelBackedQueryTransformer
                +
        ModelBackedEvidenceGrader
                ↓
        AgenticRetrievalExecutor
                ↓
        Retriever
    """

    model = FakeModel()
    retriever = FakeRetriever()

    transformer = ModelBackedQueryTransformer(
        model=model,
    )

    grader = ModelBackedEvidenceGrader(
        model=model,
    )

    executor = AgenticRetrievalExecutor(
        retriever=retriever,
        transformer=transformer,
        grader=grader,
    )

    result = await executor.retrieve(
        "AgentMesh 的 Agentic RAG 是怎么检索的？",
        user_id=11,
        top_k=3,
        max_rounds=2,
        enable_query_rewrite=True,
        enable_multi_query=False,
        enable_decomposition=False,
    )

    assert result.sufficient is True
    assert result.stopped_reason == (
        "evidence_sufficient"
    )
    assert len(result.rounds) == 1

    assert len(model.prompts) == 2

    assert (
        "[operation]"
        in model.prompts[0]
    )
    assert (
        "rewrite"
        in model.prompts[0]
    )

    assert (
        "evidence grader"
        in model.prompts[1].lower()
    )

    assert len(retriever.calls) == 1

    assert retriever.calls[0][
        "filters"
    ] == {
        "userId": 11
    }

    assert (
        retriever.calls[0][
            "query"
        ]
        == (
            "AgentMesh Agentic RAG "
            "retrieval architecture"
        )
    )

    assert (
        result.final_grade.relevance
        == pytest.approx(0.96)
    )
    assert (
        result.final_grade.coverage
        == pytest.approx(0.93)
    )
    assert (
        result.final_grade.confidence
        == pytest.approx(0.95)
    )


def test_runtime_engine_constructor_keeps_injectable_retriever_contract():
    """
    不启动 Runtime，只锁住 RuntimeEngine 的构造契约：

        RuntimeEngine(
            registry,
            retriever=...,
            memory=...,
        )

    这样 Agentic RAG 仍然能通过 FakeRetriever 做集成测试。
    """

    from app.services.engine import (
        RuntimeEngine,
    )

    signature = inspect.signature(
        RuntimeEngine.__init__
    )

    assert "registry" in (
        signature.parameters
    )
    assert "retriever" in (
        signature.parameters
    )
    assert "memory" in (
        signature.parameters
    )
