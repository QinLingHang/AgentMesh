from __future__ import annotations

from typing import Any

import pytest

from app.rag.agentic_retrieval import EvidenceGrade
from app.rag.model_intelligence import (
    ModelBackedEvidenceGrader,
    ModelBackedQueryTransformer,
)
from app.rag.runtime import RetrievalDocument, RetrievalHit


VALID_EVIDENCE = (
    '{"relevance":0.9,"coverage":0.8,"confidence":0.85,'
    '"sufficient":true,"reason":"enough"}'
)


class SequenceModel:
    model = "qwen-plus"

    def __init__(
        self,
        responses: list[str] | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.responses = list(responses or [])
        self.error = error
        self.calls = 0
        self.prompts: list[str] = []

    async def generate(self, prompt: str, on_event=None) -> str:
        self.calls += 1
        self.prompts.append(prompt)
        if self.error is not None:
            raise self.error
        if not self.responses:
            raise AssertionError("SequenceModel exhausted")
        return self.responses.pop(0)


class RecordingEvidenceFallback:
    def __init__(self) -> None:
        self.calls = 0

    async def grade(self, query: str, hits) -> EvidenceGrade:
        self.calls += 1
        return EvidenceGrade(
            relevance=0.1,
            coverage=0.1,
            confidence=0.1,
            sufficient=False,
            reason="fallback",
        )


class RecordingQueryFallback:
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
        return "fallback rewrite"

    async def multi_query(self, query: str) -> list[str]:
        self.multi_query_calls += 1
        return ["fallback multi"]

    async def decompose(self, query: str) -> list[str]:
        self.decompose_calls += 1
        return ["fallback decompose"]


def _hit() -> RetrievalHit:
    return RetrievalHit(
        document=RetrievalDocument(
            id="doc-1",
            text="Agent Alpha Gateway loses ownership after lease expiry.",
            source="unit-test",
            metadata={},
        ),
        score=0.9,
    )


@pytest.mark.asyncio
async def test_evidence_grader_recovers_from_unterminated_json_on_second_attempt():
    malformed = (
        '{"relevance":0.9,"coverage":0.8,"confidence":0.85,'
        '"sufficient":true,"reason":"unterminated"'
    )
    model = SequenceModel([malformed, VALID_EVIDENCE])
    fallback = RecordingEvidenceFallback()
    events: list[dict[str, Any]] = []
    grader = ModelBackedEvidenceGrader(
        model=model,
        fallback=fallback,
        on_rag_event=events.append,
    )

    result = await grader.grade("lease timeout?", [_hit()])

    assert result.sufficient is True
    assert model.calls == 2
    assert fallback.calls == 0
    assert "[structured-output retry]" not in model.prompts[0]
    assert "[structured-output retry]" in model.prompts[1]
    event = events[-1]
    assert event["evidenceGradeFallback"] is False
    assert event["evidenceGradeStructuredAttempts"] == 2
    assert event["evidenceGradeStructuredRetries"] == 1
    assert event["evidenceGradeStructuredRecovered"] is True
    assert (
        event["evidenceGradeStructuredRecoveryErrorType"]
        == "RESPONSE_PARSE_ERROR"
    )


@pytest.mark.asyncio
async def test_evidence_grader_recovers_from_schema_error_on_second_attempt():
    invalid_schema = (
        '{"relevance":0.9,"coverage":0.8,"confidence":0.85,'
        '"sufficient":"yes","reason":"wrong bool"}'
    )
    model = SequenceModel([invalid_schema, VALID_EVIDENCE])
    fallback = RecordingEvidenceFallback()
    events: list[dict[str, Any]] = []
    grader = ModelBackedEvidenceGrader(
        model=model,
        fallback=fallback,
        on_rag_event=events.append,
    )

    result = await grader.grade("lease timeout?", [_hit()])

    assert result.sufficient is True
    assert model.calls == 2
    assert fallback.calls == 0
    event = events[-1]
    assert event["evidenceGradeStructuredRecovered"] is True
    assert (
        event["evidenceGradeStructuredRecoveryErrorType"]
        == "RESPONSE_SCHEMA_ERROR"
    )


@pytest.mark.asyncio
async def test_evidence_grader_falls_back_only_after_three_structured_failures():
    malformed = '{"relevance":0.9'
    model = SequenceModel([malformed, malformed, malformed])
    fallback = RecordingEvidenceFallback()
    events: list[dict[str, Any]] = []
    grader = ModelBackedEvidenceGrader(
        model=model,
        fallback=fallback,
        on_rag_event=events.append,
    )

    result = await grader.grade("lease timeout?", [_hit()])

    assert result.sufficient is False
    assert model.calls == 3
    assert fallback.calls == 1
    event = events[-1]
    assert event["evidenceGradeFallback"] is True
    assert event["evidenceGradeErrorType"] == "RESPONSE_PARSE_ERROR"
    assert event["evidenceGradeStructuredAttempts"] == 3
    assert event["evidenceGradeStructuredRetries"] == 2
    assert event["evidenceGradeStructuredRecovered"] is False
    assert (
        event["evidenceGradeStructuredRecoveryErrorType"]
        == "RESPONSE_PARSE_ERROR"
    )


@pytest.mark.asyncio
async def test_evidence_grader_does_not_duplicate_provider_retry_layer():
    model = SequenceModel(error=RuntimeError("provider unavailable"))
    fallback = RecordingEvidenceFallback()
    events: list[dict[str, Any]] = []
    grader = ModelBackedEvidenceGrader(
        model=model,
        fallback=fallback,
        on_rag_event=events.append,
    )

    await grader.grade("lease timeout?", [_hit()])

    assert model.calls == 1
    assert fallback.calls == 1
    event = events[-1]
    assert event["evidenceGradeErrorType"] == "PROVIDER_ERROR"
    assert event["evidenceGradeStructuredAttempts"] == 1
    assert event["evidenceGradeStructuredRetries"] == 0


@pytest.mark.asyncio
async def test_query_rewrite_recovers_from_parse_error_without_heuristic_fallback():
    model = SequenceModel([
        '{"query":"unterminated"',
        '{"query":"Agent Alpha Gateway heartbeat lease timeout"}',
    ])
    fallback = RecordingQueryFallback()
    events: list[dict[str, Any]] = []
    transformer = ModelBackedQueryTransformer(
        model=model,
        fallback=fallback,
        on_rag_event=events.append,
    )

    result = await transformer.rewrite(
        "When does ownership expire?",
        round_index=0,
    )

    assert result == "Agent Alpha Gateway heartbeat lease timeout"
    assert model.calls == 2
    assert fallback.rewrite_calls == 0
    event = events[-1]
    assert event["fallback"] is False
    assert event["structuredOutputAttempts"] == 2
    assert event["structuredOutputRetries"] == 1
    assert event["structuredOutputRecovered"] is True
    assert event["structuredOutputRecoveryErrorType"] == "RESPONSE_PARSE_ERROR"


@pytest.mark.asyncio
async def test_multi_query_recovers_from_schema_error_without_heuristic_fallback():
    model = SequenceModel([
        '{"queries":"not-a-list"}',
        '{"queries":["lease timeout","heartbeat ownership"]}',
    ])
    fallback = RecordingQueryFallback()
    events: list[dict[str, Any]] = []
    transformer = ModelBackedQueryTransformer(
        model=model,
        fallback=fallback,
        on_rag_event=events.append,
    )

    result = await transformer.multi_query("lease timeout")

    assert result == ["lease timeout", "heartbeat ownership"]
    assert model.calls == 2
    assert fallback.multi_query_calls == 0
    event = events[-1]
    assert event["structuredOutputRecovered"] is True
    assert event["structuredOutputRecoveryErrorType"] == "RESPONSE_SCHEMA_ERROR"


@pytest.mark.asyncio
async def test_decomposition_recovers_from_parse_error_without_heuristic_fallback():
    model = SequenceModel([
        '{"queries":["one","two"]',
        '{"queries":["ownership lease","heartbeat timeout"]}',
    ])
    fallback = RecordingQueryFallback()
    events: list[dict[str, Any]] = []
    transformer = ModelBackedQueryTransformer(
        model=model,
        fallback=fallback,
        on_rag_event=events.append,
    )

    result = await transformer.decompose("analyze ownership and heartbeat")

    assert result == ["ownership lease", "heartbeat timeout"]
    assert model.calls == 2
    assert fallback.decompose_calls == 0
    event = events[-1]
    assert event["structuredOutputRecovered"] is True
    assert event["structuredOutputRecoveryErrorType"] == "RESPONSE_PARSE_ERROR"


@pytest.mark.asyncio
async def test_query_rewrite_recovers_from_duplicate_previous_query_without_fallback():
    model = SequenceModel([
        '{"query":"Agent Alpha Gateway heartbeat lease timeout"}',
        '{"query":"Agent Alpha Gateway ownership expiry missing heartbeat duration"}',
    ])
    fallback = RecordingQueryFallback()
    events: list[dict[str, Any]] = []
    transformer = ModelBackedQueryTransformer(
        model=model,
        fallback=fallback,
        on_rag_event=events.append,
    )

    result = await transformer.rewrite(
        "When does ownership expire?",
        round_index=1,
        previous_query="Agent Alpha Gateway heartbeat lease timeout",
        feedback="The evidence does not state the ownership expiry duration.",
    )

    assert result == (
        "Agent Alpha Gateway ownership expiry missing heartbeat duration"
    )
    assert model.calls == 2
    assert fallback.rewrite_calls == 0
    assert "RESPONSE_SEMANTIC_ERROR" in model.prompts[1]
    assert "duplicates previous retrieval query" in model.prompts[1]
    event = events[-1]
    assert event["fallback"] is False
    assert event["backend"] == "model"
    assert event["structuredOutputAttempts"] == 2
    assert event["structuredOutputRetries"] == 1
    assert event["structuredOutputRecovered"] is True
    assert (
        event["structuredOutputRecoveryErrorType"]
        == "RESPONSE_SEMANTIC_ERROR"
    )


@pytest.mark.asyncio
async def test_query_rewrite_falls_back_only_after_three_duplicate_semantic_failures():
    duplicate = '{"query":"Agent Alpha Gateway heartbeat lease timeout"}'
    model = SequenceModel([duplicate, duplicate, duplicate])
    fallback = RecordingQueryFallback()
    events: list[dict[str, Any]] = []
    transformer = ModelBackedQueryTransformer(
        model=model,
        fallback=fallback,
        on_rag_event=events.append,
    )

    result = await transformer.rewrite(
        "When does ownership expire?",
        round_index=1,
        previous_query="Agent Alpha Gateway heartbeat lease timeout",
        feedback="The evidence does not state the ownership expiry duration.",
    )

    assert result == "fallback rewrite"
    assert model.calls == 3
    assert fallback.rewrite_calls == 1
    event = events[-1]
    assert event["fallback"] is True
    assert event["backend"] == "heuristic"
    assert event["errorType"] == "StructuredOutputSemanticError"
    assert event["structuredOutputAttempts"] == 3
    assert event["structuredOutputRetries"] == 2
    assert event["structuredOutputRecovered"] is False
    assert (
        event["structuredOutputRecoveryErrorType"]
        == "RESPONSE_SEMANTIC_ERROR"
    )


@pytest.mark.asyncio
async def test_query_rewrite_recovers_from_whitespace_only_query_without_fallback():
    model = SequenceModel([
        '{"query":"   "}',
        '{"query":"Agent Alpha Gateway ownership expiry duration"}',
    ])
    fallback = RecordingQueryFallback()
    events: list[dict[str, Any]] = []
    transformer = ModelBackedQueryTransformer(
        model=model,
        fallback=fallback,
        on_rag_event=events.append,
    )

    result = await transformer.rewrite(
        "When does ownership expire?",
        round_index=0,
    )

    assert result == "Agent Alpha Gateway ownership expiry duration"
    assert model.calls == 2
    assert fallback.rewrite_calls == 0
    event = events[-1]
    assert event["fallback"] is False
    assert event["structuredOutputRecovered"] is True
    assert (
        event["structuredOutputRecoveryErrorType"]
        == "RESPONSE_SEMANTIC_ERROR"
    )


@pytest.mark.asyncio
async def test_multi_query_recovers_from_semantically_empty_queries_without_fallback():
    model = SequenceModel([
        '{"queries":["   ","\\t"]}',
        '{"queries":["lease timeout","heartbeat ownership"]}',
    ])
    fallback = RecordingQueryFallback()
    events: list[dict[str, Any]] = []
    transformer = ModelBackedQueryTransformer(
        model=model,
        fallback=fallback,
        on_rag_event=events.append,
    )

    result = await transformer.multi_query("lease timeout")

    assert result == ["lease timeout", "heartbeat ownership"]
    assert model.calls == 2
    assert fallback.multi_query_calls == 0
    event = events[-1]
    assert event["fallback"] is False
    assert event["structuredOutputRecovered"] is True
    assert (
        event["structuredOutputRecoveryErrorType"]
        == "RESPONSE_SEMANTIC_ERROR"
    )


@pytest.mark.asyncio
async def test_decomposition_recovers_from_semantically_empty_queries_without_fallback():
    model = SequenceModel([
        '{"queries":[" "]}',
        '{"queries":["ownership lease","heartbeat timeout"]}',
    ])
    fallback = RecordingQueryFallback()
    events: list[dict[str, Any]] = []
    transformer = ModelBackedQueryTransformer(
        model=model,
        fallback=fallback,
        on_rag_event=events.append,
    )

    result = await transformer.decompose("analyze ownership and heartbeat")

    assert result == ["ownership lease", "heartbeat timeout"]
    assert model.calls == 2
    assert fallback.decompose_calls == 0
    event = events[-1]
    assert event["fallback"] is False
    assert event["structuredOutputRecovered"] is True
    assert (
        event["structuredOutputRecoveryErrorType"]
        == "RESPONSE_SEMANTIC_ERROR"
    )
