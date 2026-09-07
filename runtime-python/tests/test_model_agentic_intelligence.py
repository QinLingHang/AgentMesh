from __future__ import annotations

from typing import Any

import pytest

from app.rag.agentic_retrieval import (
    EvidenceGrade,
)

from app.rag.model_intelligence import (
    ModelBackedEvidenceGrader,
    ModelBackedQueryTransformer,
)

from app.rag.runtime import (
    RetrievalDocument,
    RetrievalHit,
)


# ============================================================
# Fake Model
# ============================================================


class FakeModel:
    """
    用于测试 Model-backed Agentic Intelligence。

    不访问真实网络，也不依赖 API Key。
    """

    def __init__(
        self,
        responses: list[str] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.responses = list(
            responses or []
        )

        self.error = error

        self.prompts: list[str] = []

        self.on_events: list[Any] = []

    async def generate(
        self,
        prompt: str,
        on_event=None,
    ) -> str:
        self.prompts.append(
            prompt
        )

        self.on_events.append(
            on_event
        )

        if self.error is not None:
            raise self.error

        if not self.responses:
            return ""

        return self.responses.pop(0)


# ============================================================
# Fake Query Transformer Fallback
# ============================================================


class FakeQueryTransformerFallback:
    def __init__(self) -> None:
        self.rewrite_calls = 0
        self.multi_query_calls = 0
        self.decompose_calls = 0

    async def rewrite(
        self,
        query: str,
        *,
        round_index: int,
        previous_query: str | None = None,
        feedback: str | None = None,
    ) -> str:
        self.rewrite_calls += 1

        return (
            f"fallback rewrite: "
            f"{query} "
            f"round={round_index}"
        )

    async def multi_query(
        self,
        query: str,
    ) -> list[str]:
        self.multi_query_calls += 1

        return [
            query,
            f"{query} alternative",
        ]

    async def decompose(
        self,
        query: str,
    ) -> list[str]:
        self.decompose_calls += 1

        return [
            f"{query} part-1",
            f"{query} part-2",
        ]


# ============================================================
# Fake Evidence Grader Fallback
# ============================================================


class FakeEvidenceGraderFallback:
    def __init__(self) -> None:
        self.calls = 0

    async def grade(
        self,
        query: str,
        hits,
    ) -> EvidenceGrade:
        self.calls += 1

        return EvidenceGrade(
            relevance=0.38,
            coverage=0.36,
            confidence=0.41,
            sufficient=False,
            reason="fallback evidence grader",
        )


# ============================================================
# Retrieval Hit Helper
# ============================================================


def make_hit(
    *,
    document_id: str,
    text: str,
    score: float,
    source: str = "unit-test",
) -> RetrievalHit:
    return RetrievalHit(
        document=(
            RetrievalDocument(
                id=document_id,
                text=text,
                source=source,
                metadata={
                    "knowledgeBaseId": 1,
                },
            )
        ),
        score=score,
    )


# ============================================================
# 1. Model-backed Query Rewrite
# ============================================================


@pytest.mark.asyncio
async def test_model_backed_query_transformer_rewrite():
    model = FakeModel(
        responses=[
            """
            {
              "query":
                "AgentMesh MCP Failure Backoff mechanism"
            }
            """
        ]
    )

    fallback = (
        FakeQueryTransformerFallback()
    )

    transformer = (
        ModelBackedQueryTransformer(
            model=model,
            fallback=fallback,
        )
    )

    result = await transformer.rewrite(
        "AgentMesh 的 MCP Failure Backoff 是什么？",
        round_index=1,
    )

    assert result == (
        "AgentMesh MCP Failure Backoff mechanism"
    )

    assert len(
        model.prompts
    ) == 1

    assert (
        "AgentMesh 的 MCP Failure Backoff 是什么？"
        in model.prompts[0]
    )

    # model_intelligence.py 中 round_index + 1
    # 会进入 Prompt。
    assert (
        "2"
        in model.prompts[0]
    )

    assert (
        fallback.rewrite_calls
        == 0
    )


# ============================================================
# 2. Markdown JSON Fence
# ============================================================


@pytest.mark.asyncio
async def test_model_backed_query_transformer_accepts_json_fence():
    model = FakeModel(
        responses=[
            """
            ```json
            {
              "query":
                "AgentMesh adaptive retrieval architecture"
            }
            ```
            """
        ]
    )

    transformer = (
        ModelBackedQueryTransformer(
            model=model,
        )
    )

    result = await transformer.rewrite(
        "AgentMesh 自适应检索架构是什么？",
        round_index=0,
    )

    assert result == (
        "AgentMesh adaptive retrieval architecture"
    )


# ============================================================
# 3. Model-backed Multi Query
# ============================================================


@pytest.mark.asyncio
async def test_model_backed_query_transformer_multi_query():
    model = FakeModel(
        responses=[
            """
            {
              "queries": [
                "AgentMesh MCP Failure Backoff",
                "MCP server failure retry strategy",
                "AgentMesh MCP backoff mechanism"
              ]
            }
            """
        ]
    )

    fallback = (
        FakeQueryTransformerFallback()
    )

    transformer = (
        ModelBackedQueryTransformer(
            model=model,
            fallback=fallback,
        )
    )

    result = await transformer.multi_query(
        "AgentMesh 的 MCP Failure Backoff 是什么？"
    )

    assert result == [
        "AgentMesh MCP Failure Backoff",
        "MCP server failure retry strategy",
        "AgentMesh MCP backoff mechanism",
    ]

    assert (
        fallback.multi_query_calls
        == 0
    )


# ============================================================
# 4. Multi Query Normalize / Deduplicate / Limit
# ============================================================


@pytest.mark.asyncio
async def test_model_backed_query_transformer_normalizes_multi_query():
    model = FakeModel(
        responses=[
            """
            {
              "queries": [
                "  AgentMesh MCP  ",
                "agentmesh mcp",
                "Failure Backoff",
                "Retry Strategy",
                "Recovery Policy",
                "Extra Query"
              ]
            }
            """
        ]
    )

    transformer = (
        ModelBackedQueryTransformer(
            model=model,
        )
    )

    result = await transformer.multi_query(
        "AgentMesh MCP"
    )

    # model_intelligence.py：
    # - 去首尾和连续空格
    # - 大小写不敏感去重
    # - Model-backed multi-query 最多保留 4 条
    assert result == [
        "AgentMesh MCP",
        "Failure Backoff",
        "Retry Strategy",
        "Recovery Policy",
    ]


# ============================================================
# 5. Model-backed Query Decomposition
# ============================================================


@pytest.mark.asyncio
async def test_model_backed_query_transformer_decompose():
    model = FakeModel(
        responses=[
            """
            {
              "queries": [
                "AgentMesh 如何发现 MCP Server？",
                "MCP Failure Backoff 如何工作？",
                "失败后的 Server 何时恢复？"
              ]
            }
            """
        ]
    )

    fallback = (
        FakeQueryTransformerFallback()
    )

    transformer = (
        ModelBackedQueryTransformer(
            model=model,
            fallback=fallback,
        )
    )

    result = await transformer.decompose(
        (
            "分析 AgentMesh MCP Server "
            "发现、失败退避和恢复机制"
        )
    )

    assert result == [
        "AgentMesh 如何发现 MCP Server？",
        "MCP Failure Backoff 如何工作？",
        "失败后的 Server 何时恢复？",
    ]

    assert (
        fallback.decompose_calls
        == 0
    )


# ============================================================
# 6. Invalid JSON -> Query Fallback
# ============================================================


@pytest.mark.asyncio
async def test_model_backed_query_transformer_falls_back_on_invalid_json():
    model = FakeModel(
        responses=[
            "this is not valid json"
        ]
    )

    fallback = (
        FakeQueryTransformerFallback()
    )

    transformer = (
        ModelBackedQueryTransformer(
            model=model,
            fallback=fallback,
        )
    )

    result = await transformer.rewrite(
        "original query",
        round_index=3,
    )

    assert result == (
        "fallback rewrite: "
        "original query "
        "round=3"
    )

    assert (
        fallback.rewrite_calls
        == 1
    )


# ============================================================
# 7. Model Error -> Query Fallback + RAG Event
# ============================================================


@pytest.mark.asyncio
async def test_model_backed_query_transformer_falls_back_on_model_error():
    model = FakeModel(
        error=RuntimeError(
            "model unavailable"
        )
    )

    fallback = (
        FakeQueryTransformerFallback()
    )

    rag_events: list[
        dict[str, Any]
    ] = []

    transformer = (
        ModelBackedQueryTransformer(
            model=model,
            fallback=fallback,
            on_rag_event=(
                rag_events.append
            ),
        )
    )

    result = await transformer.multi_query(
        "AgentMesh retrieval"
    )

    assert result == [
        "AgentMesh retrieval",
        "AgentMesh retrieval alternative",
    ]

    assert (
        fallback.multi_query_calls
        == 1
    )

    assert len(
        rag_events
    ) == 1

    assert (
        rag_events[0][
            "fallback"
        ]
        is True
    )

    assert (
        rag_events[0][
            "backend"
        ]
        == "heuristic"
    )

    assert (
        rag_events[0][
            "operation"
        ]
        == "multi_query"
    )


# ============================================================
# 8. Model-backed Evidence Grader
# ============================================================


@pytest.mark.asyncio
async def test_model_backed_evidence_grader():
    model = FakeModel(
        responses=[
            """
            {
              "relevance": 0.96,
              "coverage": 0.91,
              "confidence": 0.93,
              "sufficient": true,
              "reason":
                "The retrieved evidence directly answers the query."
            }
            """
        ]
    )

    fallback = (
        FakeEvidenceGraderFallback()
    )

    grader = (
        ModelBackedEvidenceGrader(
            model=model,
            fallback=fallback,
        )
    )

    hits = [
        make_hit(
            document_id="doc-1",
            text=(
                "MCP Failure Backoff temporarily "
                "blocks repeatedly failing servers."
            ),
            score=0.91,
        )
    ]

    result = await grader.grade(
        "What is MCP Failure Backoff?",
        hits,
    )

    assert isinstance(
        result,
        EvidenceGrade,
    )

    assert (
        result.relevance
        == pytest.approx(
            0.96
        )
    )

    assert (
        result.coverage
        == pytest.approx(
            0.91
        )
    )

    assert (
        result.confidence
        == pytest.approx(
            0.93
        )
    )

    assert (
        result.sufficient
        is True
    )

    assert (
        result.reason
        == (
            "The retrieved evidence "
            "directly answers the query."
        )
    )

    assert (
        fallback.calls
        == 0
    )


# ============================================================
# 9. Evidence Prompt Contains Query + Evidence
# ============================================================


@pytest.mark.asyncio
async def test_model_backed_evidence_grader_prompt_contains_evidence():
    model = FakeModel(
        responses=[
            """
            {
              "relevance": 0.92,
              "coverage": 0.86,
              "confidence": 0.88,
              "sufficient": true,
              "reason": "relevant evidence"
            }
            """
        ]
    )

    grader = (
        ModelBackedEvidenceGrader(
            model=model,
        )
    )

    hits = [
        make_hit(
            document_id="doc-42",
            text=(
                "AgentMesh uses adaptive "
                "retrieval routing."
            ),
            score=0.86,
        )
    ]

    await grader.grade(
        "How does AgentMesh retrieval work?",
        hits,
    )

    assert len(
        model.prompts
    ) == 1

    prompt = (
        model.prompts[0]
    )

    assert (
        "How does AgentMesh retrieval work?"
        in prompt
    )

    assert (
        "AgentMesh uses adaptive retrieval routing."
        in prompt
    )

    assert (
        "0.86"
        in prompt
    )

    assert (
        "doc-42"
        in prompt
    )


# ============================================================
# 10. Evidence JSON Fence
# ============================================================


@pytest.mark.asyncio
async def test_model_backed_evidence_grader_accepts_json_fence():
    model = FakeModel(
        responses=[
            """
            ```json
            {
              "relevance": 0.84,
              "coverage": 0.79,
              "confidence": 0.81,
              "sufficient": true,
              "reason": "evidence is sufficient"
            }
            ```
            """
        ]
    )

    grader = (
        ModelBackedEvidenceGrader(
            model=model,
        )
    )

    hits = [
        make_hit(
            document_id="doc-1",
            text="AgentMesh retrieval evidence.",
            score=0.8,
        )
    ]

    result = await grader.grade(
        "test query",
        hits,
    )

    assert (
        result.relevance
        == pytest.approx(
            0.84
        )
    )

    assert (
        result.coverage
        == pytest.approx(
            0.79
        )
    )

    assert (
        result.confidence
        == pytest.approx(
            0.81
        )
    )

    assert (
        result.sufficient
        is True
    )

    assert (
        result.reason
        == "evidence is sufficient"
    )


# ============================================================
# 11. Empty Evidence Bypasses Model
# ============================================================


@pytest.mark.asyncio
async def test_model_backed_evidence_grader_empty_hits_uses_fallback_without_model():
    model = FakeModel(
        responses=[
            """
            {
              "relevance": 1.0,
              "coverage": 1.0,
              "confidence": 1.0,
              "sufficient": true,
              "reason": "should never be used"
            }
            """
        ]
    )

    fallback = (
        FakeEvidenceGraderFallback()
    )

    grader = (
        ModelBackedEvidenceGrader(
            model=model,
            fallback=fallback,
        )
    )

    result = await grader.grade(
        "test query",
        [],
    )

    assert (
        result.confidence
        == pytest.approx(
            0.41
        )
    )

    assert (
        result.sufficient
        is False
    )

    assert (
        fallback.calls
        == 1
    )

    # 当前正式实现的设计：
    # 没有 evidence 时，不浪费一次 LLM 调用。
    assert (
        model.prompts
        == []
    )


# ============================================================
# 12. Invalid Evidence JSON -> Fallback
# ============================================================


@pytest.mark.asyncio
async def test_model_backed_evidence_grader_falls_back_on_invalid_json():
    model = FakeModel(
        responses=[
            "not-json"
        ]
    )

    fallback = (
        FakeEvidenceGraderFallback()
    )

    grader = (
        ModelBackedEvidenceGrader(
            model=model,
            fallback=fallback,
        )
    )

    hits = [
        make_hit(
            document_id="doc-1",
            text="some evidence",
            score=0.7,
        )
    ]

    result = await grader.grade(
        "test query",
        hits,
    )

    assert (
        result.confidence
        == pytest.approx(
            0.41
        )
    )

    assert (
        result.sufficient
        is False
    )

    assert (
        result.reason
        == "fallback evidence grader"
    )

    assert (
        fallback.calls
        == 1
    )


# ============================================================
# 13. Model Error -> Evidence Fallback
# ============================================================


@pytest.mark.asyncio
async def test_model_backed_evidence_grader_falls_back_on_model_error():
    model = FakeModel(
        error=TimeoutError(
            "model timeout"
        )
    )

    fallback = (
        FakeEvidenceGraderFallback()
    )

    grader = (
        ModelBackedEvidenceGrader(
            model=model,
            fallback=fallback,
        )
    )

    hits = [
        make_hit(
            document_id="doc-1",
            text="some evidence",
            score=0.7,
        )
    ]

    result = await grader.grade(
        "test query",
        hits,
    )

    assert (
        result.sufficient
        is False
    )

    assert (
        result.confidence
        == pytest.approx(
            0.41
        )
    )

    assert (
        fallback.calls
        == 1
    )


# ============================================================
# 14. Invalid Score -> Evidence Fallback
# ============================================================


@pytest.mark.asyncio
async def test_model_backed_evidence_grader_rejects_invalid_confidence():
    model = FakeModel(
        responses=[
            """
            {
              "relevance": 0.9,
              "coverage": 0.9,
              "confidence": 1.8,
              "sufficient": true,
              "reason": "invalid confidence"
            }
            """
        ]
    )

    fallback = (
        FakeEvidenceGraderFallback()
    )

    grader = (
        ModelBackedEvidenceGrader(
            model=model,
            fallback=fallback,
        )
    )

    hits = [
        make_hit(
            document_id="doc-1",
            text="some evidence",
            score=0.7,
        )
    ]

    result = await grader.grade(
        "test query",
        hits,
    )

    assert (
        result.confidence
        == pytest.approx(
            0.41
        )
    )

    assert (
        result.sufficient
        is False
    )

    assert (
        fallback.calls
        == 1
    )


# ============================================================
# 15. Invalid Boolean Shape -> Evidence Fallback
# ============================================================


@pytest.mark.asyncio
async def test_model_backed_evidence_grader_rejects_invalid_sufficient_shape():
    model = FakeModel(
        responses=[
            """
            {
              "relevance": 0.9,
              "coverage": 0.9,
              "confidence": 0.9,
              "sufficient": {"value": true},
              "reason": "wrong type"
            }
            """
        ]
    )

    fallback = (
        FakeEvidenceGraderFallback()
    )

    grader = (
        ModelBackedEvidenceGrader(
            model=model,
            fallback=fallback,
        )
    )

    hits = [
        make_hit(
            document_id="doc-1",
            text="some evidence",
            score=0.7,
        )
    ]

    result = await grader.grade(
        "test query",
        hits,
    )

    assert (
        result.confidence
        == pytest.approx(
            0.41
        )
    )

    assert (
        result.sufficient
        is False
    )

    assert (
        fallback.calls
        == 1
    )
@pytest.mark.asyncio
async def test_model_backed_query_transformer_uses_constrained_feedback_prompt():

    model = FakeModel(
        responses=[
            """
            {
              "query":
                "AgentMesh MCP Failure Backoff retry logic timing recovery conditions"
            }
            """
        ]
    )

    rag_events: list[
        dict[str, Any]
    ] = []

    transformer = (
        ModelBackedQueryTransformer(
            model=model,
            on_rag_event=(
                rag_events.append
            ),
        )
    )

    result = await transformer.rewrite(
        (
            "Please explain the AgentMesh "
            "MCP Failure Backoff mechanism "
            "and how recovery works."
        ),
        round_index=1,
        previous_query=(
            "AgentMesh MCP Failure "
            "Backoff mechanism"
        ),
        feedback=(
            "The evidence does not explain "
            "retry logic, timing, or "
            "recovery conditions."
        ),
    )

    assert result == (
        "AgentMesh MCP Failure Backoff "
        "retry logic timing recovery conditions"
    )

    assert len(model.prompts) == 1

    prompt = model.prompts[0]

    # Feedback 必须真正进入 Prompt。
    assert (
        "retry logic, timing, or "
        "recovery conditions"
        in prompt
    )

    # 禁止根据通用知识脑补实现。
    assert (
        "Do NOT invent implementation details"
        in prompt
    )

    assert (
        "Do not speculate about how those"
        in prompt
    )

    # Query 应保持精炼。
    assert (
        "2 to 4 missing concepts"
        in prompt
    )

    assert (
        'Do not include examples such as "e.g."'
        in prompt
    )

    assert (
        "preferably below 30 words"
        in prompt
    )

    assert rag_events[-1][
        "backend"
    ] == "model"

    assert rag_events[-1][
        "fallback"
    ] is False

    assert rag_events[-1][
        "feedbackAware"
    ] is True
