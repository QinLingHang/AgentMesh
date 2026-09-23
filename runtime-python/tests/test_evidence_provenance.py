import pytest

from app.rag import (
    RetrievalDocument,
    RetrievalHit,
)

from app.rag.provenance import (
    build_evidence_provenance,
)


def _make_hit(
    *,
    document_id: str,
    source: str,
    score: float,
    metadata: dict | None = None,
) -> RetrievalHit:

    return RetrievalHit(
        document=(
            RetrievalDocument(
                id=(
                    document_id
                ),
                text=(
                    f"Evidence from {source}"
                ),
                source=(
                    source
                ),
                metadata=(
                    metadata
                    or {}
                ),
            )
        ),
        score=(
            score
        ),
    )


def test_provenance_assigns_request_local_citation_ids():

    hits = [
        _make_hit(
            document_id="doc-a",
            source="source-a",
            score=0.90,
        ),
        _make_hit(
            document_id="doc-b",
            source="source-b",
            score=0.80,
        ),
    ]

    provenance = (
        build_evidence_provenance(
            hits
        )
    )

    assert (
        len(provenance)
        == 2
    )

    assert (
        provenance[
            0
        ]
        .citation_id
        == 1
    )

    assert (
        provenance[
            0
        ]
        .citation_label
        == "[1]"
    )

    assert (
        provenance[
            1
        ]
        .citation_id
        == 2
    )

    assert (
        provenance[
            1
        ]
        .citation_label
        == "[2]"
    )


def test_provenance_preserves_final_retrieval_order():

    hits = [
        _make_hit(
            document_id="doc-high",
            source="high",
            score=0.91,
        ),
        _make_hit(
            document_id="doc-low",
            source="low",
            score=0.40,
        ),
    ]

    provenance = (
        build_evidence_provenance(
            hits
        )
    )

    assert [
        item.document_id
        for item
        in provenance
    ] == [
        "doc-high",
        "doc-low",
    ]

    assert [
        item.score
        for item
        in provenance
    ] == [
        0.91,
        0.40,
    ]


def test_provenance_deduplicates_document_id():

    duplicate_a = (
        _make_hit(
            document_id="doc-a",
            source="source-a",
            score=0.90,
        )
    )

    duplicate_b = (
        _make_hit(
            document_id="doc-a",
            source="source-a",
            score=0.70,
        )
    )

    provenance = (
        build_evidence_provenance(
            [
                duplicate_a,
                duplicate_b,
            ]
        )
    )

    assert (
        len(provenance)
        == 1
    )

    assert (
        provenance[
            0
        ]
        .citation_id
        == 1
    )

    # The first ranked occurrence wins.
    assert (
        provenance[
            0
        ]
        .score
        == 0.90
    )


def test_provenance_extracts_chunk_identity_and_filters_runtime_metadata():

    hit = (
        _make_hit(
            document_id=(
                "chunk-de4e40"
            ),
            source=(
                "agentmesh-mcp"
            ),
            score=(
                0.734388
            ),
            metadata={
                "userId":
                    1,

                "documentType":
                    "agentmesh-demo",

                "chunkIndex":
                    0,

                "start":
                    0,

                "end":
                    128,

                "retrievalMode":
                    "dense+bm25+rrf",

                "rrfScore":
                    0.0327,

                "reranker":
                    "qwen3-rerank",

                "preRerankScore":
                    0.0327,

                "modelRerankScore":
                    0.734388,

                "ragDiagnostics": {
                    "backend":
                        "hybrid_milvus"
                },

                # Future source metadata should survive.
                "title":
                    "AgentMesh MCP",

                "page":
                    3,
            },
        )
    )

    provenance = (
        build_evidence_provenance(
            [
                hit
            ]
        )
    )

    item = (
        provenance[
            0
        ]
    )

    assert (
        item.document_id
        == "chunk-de4e40"
    )

    assert (
        item.source
        == "agentmesh-mcp"
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
        == 128
    )

    # Source metadata remains available.
    assert (
        item.metadata[
            "title"
        ]
        == "AgentMesh MCP"
    )

    assert (
        item.metadata[
            "page"
        ]
        == 3
    )

    # Sensitive / runtime metadata must not leak.
    assert (
        "userId"
        not in item.metadata
    )

    assert (
        "retrievalMode"
        not in item.metadata
    )

    assert (
        "rrfScore"
        not in item.metadata
    )

    assert (
        "reranker"
        not in item.metadata
    )

    assert (
        "modelRerankScore"
        not in item.metadata
    )

    assert (
        "ragDiagnostics"
        not in item.metadata
    )


def test_provenance_rejects_missing_document_identity():

    hit = (
        _make_hit(
            document_id="",
            source="unknown",
            score=0.5,
        )
    )

    with pytest.raises(
        ValueError,
        match=(
            "requires non-empty "
            "document id"
        ),
    ):
        build_evidence_provenance(
            [
                hit
            ]
        )

def test_unique_evidence_selection_keeps_prompt_and_provenance_aligned():
    """Regression: [A, A, B] must never render [2] with A's body."""
    from app.rag.provenance import select_unique_evidence_hits

    first = _make_hit(document_id="doc-a", source="a", score=0.95)
    duplicated = _make_hit(document_id="doc-a", source="a-again", score=0.70)
    second = _make_hit(document_id="doc-b", source="b", score=0.80)
    selected = select_unique_evidence_hits([first, duplicated, second], limit=4)
    provenance = build_evidence_provenance(selected)
    assert [hit.document.id for hit in selected] == ["doc-a", "doc-b"]
    assert [(ref.citation_id, ref.document_id) for ref in provenance] == [
        (1, "doc-a"), (2, "doc-b"),
    ]
    assert all(ref.document_id == hit.document.id for ref, hit in zip(provenance, selected))


def test_unique_evidence_selection_rejects_missing_identity_even_after_limit():
    from app.rag.provenance import select_unique_evidence_hits

    with pytest.raises(ValueError, match="document id"):
        select_unique_evidence_hits([_make_hit(document_id="", source="no-id", score=0.9)])


def test_unique_evidence_selection_rejects_nonpositive_limit():
    from app.rag.provenance import select_unique_evidence_hits

    with pytest.raises(ValueError, match="limit must be positive"):
        select_unique_evidence_hits([], limit=0)
