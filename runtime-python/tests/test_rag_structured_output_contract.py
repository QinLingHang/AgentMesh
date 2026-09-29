from __future__ import annotations

from typing import Any

import pytest

from app.rag.agentic_retrieval import EvidenceGrade
from app.rag.model_intelligence import ModelBackedEvidenceGrader
from app.rag.runtime import RetrievalDocument, RetrievalHit


class FakeModel:
    model = "qwen-plus"

    def __init__(
        self,
        *,
        response: str = "",
        error: Exception | None = None,
    ) -> None:
        self.response = response
        self.error = error

    async def generate(self, prompt: str, on_event=None) -> str:
        if self.error is not None:
            raise self.error
        return self.response


class RecordingFallback:
    def __init__(self) -> None:
        self.calls = 0

    async def grade(self, query: str, hits) -> EvidenceGrade:
        self.calls += 1
        return EvidenceGrade(
            relevance=0.2,
            coverage=0.2,
            confidence=0.2,
            sufficient=False,
            reason="fallback",
        )


def _hit() -> RetrievalHit:
    return RetrievalHit(
        document=RetrievalDocument(
            id="doc-1",
            text="Agent Alpha Gateway loses ownership after the lease expires.",
            source="unit-test",
            metadata={},
        ),
        score=0.9,
    )


def _valid_payload(reason: str = "enough") -> str:
    return (
        '{"relevance":0.9,"coverage":0.8,"confidence":0.85,'
        f'"sufficient":true,"reason":{reason!r}}}'
    ).replace("'", '"')


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        '{"relevance":0.9,"coverage":0.8,"confidence":0.85,"sufficient":true,"reason":"enough"}',
        '```json\n{"relevance":0.9,"coverage":0.8,"confidence":0.85,"sufficient":true,"reason":"enough"}\n```',
        'Result follows:\n{"relevance":0.9,"coverage":0.8,"confidence":0.85,"sufficient":true,"reason":"enough"}',
        '{"relevance":0.9,"coverage":0.8,"confidence":0.85,"sufficient":true,"reason":"enough"}\nDone.',
        'prefix {not-json} then {"relevance":0.9,"coverage":0.8,"confidence":0.85,"sufficient":true,"reason":"enough"} suffix',
        '{"relevance":0.9,"coverage":0.8,"confidence":0.85,"sufficient":true,"reason":"contains {brace} safely"}',
        '{"relevance":0.9,"coverage":0.8,"confidence":0.85,"sufficient":true,"reason":"escaped \\\"quote\\\" and {brace}"}',
        '{"relevance":1,"coverage":1,"confidence":1,"sufficient":true,"reason":"integer scores are valid numeric values","meta":{"nested":true}}',
    ],
)
async def test_evidence_grader_accepts_supported_json_wrapping(response: str):
    fallback = RecordingFallback()
    events: list[dict[str, Any]] = []
    grader = ModelBackedEvidenceGrader(
        model=FakeModel(response=response),
        fallback=fallback,
        on_rag_event=events.append,
    )

    result = await grader.grade("lease timeout?", [_hit()])

    assert result.sufficient is True
    assert fallback.calls == 0
    assert events[-1]["fallback"] is False
    assert events[-1]["requestedEvidenceGrader"] == "qwen-plus"
    assert events[-1]["effectiveEvidenceGrader"] == "qwen-plus"
    assert events[-1]["evidenceGradeFallback"] is False


@pytest.mark.asyncio
async def test_evidence_grader_reports_parse_error_before_fallback():
    fallback = RecordingFallback()
    events: list[dict[str, Any]] = []
    grader = ModelBackedEvidenceGrader(
        model=FakeModel(response="No JSON was returned."),
        fallback=fallback,
        on_rag_event=events.append,
    )

    result = await grader.grade("lease timeout?", [_hit()])

    assert result.sufficient is False
    assert fallback.calls == 1
    event = events[-1]
    assert event["evidenceGradeFallback"] is True
    assert event["evidenceGradeErrorType"] == "RESPONSE_PARSE_ERROR"
    assert event["requestedEvidenceGrader"] == "qwen-plus"
    assert event["effectiveEvidenceGrader"] == "heuristic"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        '{"relevance":0.9,"coverage":0.8,"confidence":0.85,"sufficient":"yes","reason":"wrong bool"}',
        '{"relevance":"0.9","coverage":0.8,"confidence":0.85,"sufficient":true,"reason":"wrong score type"}',
        '{"relevance":0.9,"coverage":0.8,"confidence":0.85,"reason":"missing sufficient"}',
        '{"relevance":1.2,"coverage":0.8,"confidence":0.85,"sufficient":true,"reason":"out of range"}',
    ],
)
async def test_evidence_grader_reports_schema_error_before_fallback(response: str):
    fallback = RecordingFallback()
    events: list[dict[str, Any]] = []
    grader = ModelBackedEvidenceGrader(
        model=FakeModel(response=response),
        fallback=fallback,
        on_rag_event=events.append,
    )

    await grader.grade("lease timeout?", [_hit()])

    assert fallback.calls == 1
    event = events[-1]
    assert event["evidenceGradeErrorType"] == "RESPONSE_SCHEMA_ERROR"
    assert event["evidenceGradeFallback"] is True


@pytest.mark.asyncio
async def test_evidence_grader_reports_provider_error_before_fallback():
    fallback = RecordingFallback()
    events: list[dict[str, Any]] = []
    grader = ModelBackedEvidenceGrader(
        model=FakeModel(error=RuntimeError("provider unavailable")),
        fallback=fallback,
        on_rag_event=events.append,
    )

    await grader.grade("lease timeout?", [_hit()])

    assert fallback.calls == 1
    event = events[-1]
    assert event["evidenceGradeErrorType"] == "PROVIDER_ERROR"
    assert event["errorType"] == "RuntimeError"
    assert "provider unavailable" in event["evidenceGradeError"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        (
            '{"wrapper": '
            '{"relevance":0.9,"coverage":0.8,"confidence":0.85,'
            '"sufficient":true,"reason":"inner"}'
        ),
        (
            '{"wrapper": '
            '{"relevance":0.9,"coverage":0.8,"confidence":0.85,'
            '"sufficient":true,"reason":"inner"} trailing}'
        ),
    ],
)
async def test_evidence_grader_rejects_malformed_outer_object_with_valid_inner_payload(
    response: str,
):
    fallback = RecordingFallback()
    events: list[dict[str, Any]] = []
    grader = ModelBackedEvidenceGrader(
        model=FakeModel(response=response),
        fallback=fallback,
        on_rag_event=events.append,
    )

    result = await grader.grade(
        "lease timeout?",
        [_hit()],
    )

    assert result.sufficient is False
    assert fallback.calls == 1
    event = events[-1]
    assert event["evidenceGradeFallback"] is True
    assert event["evidenceGradeErrorType"] == "RESPONSE_PARSE_ERROR"
    assert event["requestedEvidenceGrader"] == "qwen-plus"
    assert event["effectiveEvidenceGrader"] == "heuristic"


@pytest.mark.asyncio
async def test_evidence_grader_skips_unmatched_non_json_prose_brace_before_valid_payload():
    fallback = RecordingFallback()
    events: list[dict[str, Any]] = []
    response = (
        'prefix {not-json prose then '
        '{"relevance":0.9,"coverage":0.8,"confidence":0.85,'
        '"sufficient":true,"reason":"independent payload"}'
    )
    grader = ModelBackedEvidenceGrader(
        model=FakeModel(response=response),
        fallback=fallback,
        on_rag_event=events.append,
    )

    result = await grader.grade(
        "lease timeout?",
        [_hit()],
    )

    assert result.sufficient is True
    assert fallback.calls == 0
    assert events[-1]["evidenceGradeFallback"] is False


@pytest.mark.asyncio
async def test_evidence_grader_skips_balanced_malformed_outer_block_before_later_independent_json():
    fallback = RecordingFallback()
    events: list[dict[str, Any]] = []
    response = (
        'prefix {"wrapper": '
        '{"relevance":0.1,"coverage":0.1,"confidence":0.1,'
        '"sufficient":false,"reason":"nested must not be promoted"} trailing} '
        'then {"relevance":0.9,"coverage":0.8,"confidence":0.85,'
        '"sufficient":true,"reason":"independent payload"}'
    )
    grader = ModelBackedEvidenceGrader(
        model=FakeModel(response=response),
        fallback=fallback,
        on_rag_event=events.append,
    )

    result = await grader.grade(
        "lease timeout?",
        [_hit()],
    )

    assert result.sufficient is True
    assert result.reason == "independent payload"
    assert fallback.calls == 0
    assert events[-1]["evidenceGradeFallback"] is False
