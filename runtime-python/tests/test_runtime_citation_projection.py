import pytest

from app.rag import (
    EvidenceProvenance,
)

from app.services.citation_projection import (
    project_used_citations,
)


def _evidence(
    *,
    citation_id: int,
    document_id: str,
    source: str,
    score: float,
    document_type: str | None = None,
    chunk_index: int | None = None,
    start: int | None = None,
    end: int | None = None,
) -> EvidenceProvenance:

    return EvidenceProvenance(
        citation_id=(
            citation_id
        ),

        document_id=(
            document_id
        ),

        source=(
            source
        ),

        score=(
            score
        ),

        document_type=(
            document_type
        ),

        chunk_index=(
            chunk_index
        ),

        start=(
            start
        ),

        end=(
            end
        ),

        metadata={},
    )


def test_projection_returns_only_used_citations():

    provenance = [
        _evidence(
            citation_id=1,
            document_id="doc-rag",
            source="agentmesh-rag",
            score=0.9551758138,
        ),

        _evidence(
            citation_id=2,
            document_id="doc-mcp",
            source="agentmesh-mcp",
            score=0.5964,
        ),

        _evidence(
            citation_id=3,
            document_id="doc-deployment",
            source="agentmesh-deployment",
            score=0.5635,
        ),
    ]

    result = project_used_citations(
        provenance=provenance,
        used_citation_ids=[
            1,
            1,
        ],
    )

    assert (
        len(result)
        == 1
    )

    assert (
        result[
            0
        ]
        .citation_id
        == 1
    )

    assert (
        result[
            0
        ]
        .label
        == "[1]"
    )

    assert (
        result[
            0
        ]
        .source
        == "agentmesh-rag"
    )


def test_projection_preserves_first_use_order():

    provenance = [
        _evidence(
            citation_id=1,
            document_id="doc-1",
            source="source-1",
            score=0.9,
        ),

        _evidence(
            citation_id=2,
            document_id="doc-2",
            source="source-2",
            score=0.8,
        ),

        _evidence(
            citation_id=3,
            document_id="doc-3",
            source="source-3",
            score=0.7,
        ),
    ]

    result = project_used_citations(
        provenance=provenance,
        used_citation_ids=[
            3,
            1,
            3,
        ],
    )

    assert [
        item.citation_id
        for item
        in result
    ] == [
        3,
        1,
    ]


def test_projection_preserves_public_provenance_fields():

    provenance = [
        _evidence(
            citation_id=1,
            document_id=(
                "chunk_dc85b0"
            ),
            source=(
                "agentmesh-rag"
            ),
            score=(
                0.9551758138
            ),
            document_type=(
                "agentmesh-demo"
            ),
            chunk_index=0,
            start=0,
            end=127,
        )
    ]

    result = project_used_citations(
        provenance=provenance,
        used_citation_ids=[
            1
        ],
    )

    item = result[
        0
    ]

    assert (
        item.citation_id
        == 1
    )

    assert (
        item.label
        == "[1]"
    )

    assert (
        item.document_id
        == "chunk_dc85b0"
    )

    assert (
        item.source
        == "agentmesh-rag"
    )

    assert (
        item.score
        == 0.955176
    )

    assert (
        item.document_type
        == "agentmesh-demo"
    )

    assert (
        item.chunk_index
        == 0
    )

    assert (
        item.start
        == 0
    )

    assert (
        item.end
        == 127
    )


def test_projection_with_no_used_citations_returns_empty_list():

    provenance = [
        _evidence(
            citation_id=1,
            document_id="doc-1",
            source="source-1",
            score=0.9,
        )
    ]

    result = project_used_citations(
        provenance=provenance,
        used_citation_ids=[],
    )

    assert (
        result
        == []
    )


def test_projection_rejects_unknown_citation_id():

    provenance = [
        _evidence(
            citation_id=1,
            document_id="doc-1",
            source="source-1",
            score=0.9,
        )
    ]

    with pytest.raises(
        ValueError,
        match=r"\[99\]",
    ):
        project_used_citations(
            provenance=provenance,
            used_citation_ids=[
                99
            ],
        )