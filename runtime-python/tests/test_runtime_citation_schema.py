from app.schemas import (
    RuntimeCitation,
    RuntimeResponse,
)


def test_runtime_citation_serializes_with_public_aliases():

    citation = RuntimeCitation(
        citation_id=1,
        label="[1]",
        document_id="chunk-001",
        source="agentmesh-rag",
        score=0.955176,
        document_type="agentmesh-demo",
        chunk_index=0,
        start=0,
        end=127,
    )

    payload = citation.model_dump(
        by_alias=True
    )

    assert payload == {
        "citationId":
            1,

        "label":
            "[1]",

        "documentId":
            "chunk-001",

        "source":
            "agentmesh-rag",

        "score":
            0.955176,

        "documentType":
            "agentmesh-demo",

        "chunkIndex":
            0,

        "start":
            0,

        "end":
            127,
    }


def test_runtime_response_citations_are_backward_compatible():

    field = (
        RuntimeResponse
        .model_fields[
            "citations"
        ]
    )

    assert (
        field.default_factory
        is not None
    )

    assert (
        field.default_factory()
        == []
    )