from app.rag import (
    EvidenceProvenance,
)

from app.services.citation_validator import (
    guard_answer_citations,
)


def _evidence(
    citation_id: int,
) -> EvidenceProvenance:

    return EvidenceProvenance(
        citation_id=(
            citation_id
        ),

        document_id=(
            f"doc-{citation_id}"
        ),

        source=(
            f"source-{citation_id}"
        ),

        score=0.9,

        metadata={},
    )


def test_valid_repeated_citations_are_allowed():

    provenance = [
        _evidence(1),
        _evidence(2),
    ]

    answer = (
        "AgentMesh uses Milvus [1]. "
        "It also supports BM25 [1]."
    )

    result = (
        guard_answer_citations(
            task=(
                "Explain retrieval."
            ),
            answer=answer,
            provenance=provenance,
            require_citation=True,
        )
    )

    assert (
        result.passed
        is True
    )

    assert (
        result.action
        == "allow"
    )

    assert (
        result.answer
        == answer
    )

    assert (
        result.citations
        == (
            1,
            1,
        )
    )

    assert (
        result.invalid_citations
        == ()
    )

    assert (
        result.violations
        == ()
    )


def test_unknown_citation_is_rejected():

    provenance = [
        _evidence(1),
        _evidence(2),
    ]

    result = (
        guard_answer_citations(
            task=(
                "Explain retrieval."
            ),
            answer=(
                "AgentMesh uses Milvus [5]."
            ),
            provenance=provenance,
            require_citation=True,
        )
    )

    assert (
        result.passed
        is False
    )

    assert (
        result.action
        == "safe_rejection"
    )

    assert (
        result.citations
        == (5,)
    )

    assert (
        result.invalid_citations
        == (5,)
    )

    assert (
        "unknown_citation:[5]"
        in result.violations
    )

    assert (
        "[5]"
        not in result.answer
    )


def test_missing_required_citation_is_rejected():

    provenance = [
        _evidence(1),
    ]

    result = (
        guard_answer_citations(
            task=(
                "Explain retrieval."
            ),
            answer=(
                "AgentMesh uses Milvus."
            ),
            provenance=provenance,
            require_citation=True,
        )
    )

    assert (
        result.passed
        is False
    )

    assert (
        result.action
        == "safe_rejection"
    )

    assert (
        "missing_required_citation"
        in result.violations
    )


def test_missing_optional_citation_is_allowed():

    provenance = [
        _evidence(1),
    ]

    answer = (
        "The requested details cannot "
        "be determined."
    )

    result = (
        guard_answer_citations(
            task=(
                "Explain an unknown detail."
            ),
            answer=answer,
            provenance=provenance,
            require_citation=False,
        )
    )

    assert (
        result.passed
        is True
    )

    assert (
        result.action
        == "allow"
    )

    assert (
        result.answer
        == answer
    )


def test_no_provenance_and_no_citations_is_not_applicable():

    answer = "Hello."

    result = (
        guard_answer_citations(
            task="Hello",
            answer=answer,
            provenance=[],
            require_citation=False,
        )
    )

    assert (
        result.passed
        is True
    )

    assert (
        result.action
        == "not_applicable"
    )

    assert (
        result.answer
        == answer
    )


def test_citation_without_provenance_is_rejected():

    result = (
        guard_answer_citations(
            task=(
                "Answer without RAG."
            ),
            answer=(
                "This claim is supported [1]."
            ),
            provenance=[],
            require_citation=False,
        )
    )

    assert (
        result.passed
        is False
    )

    assert (
        result.action
        == "safe_rejection"
    )

    assert (
        result.invalid_citations
        == (1,)
    )

    assert (
        "unknown_citation:[1]"
        in result.violations
    )