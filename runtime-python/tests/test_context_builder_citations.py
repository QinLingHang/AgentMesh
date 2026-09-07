from app.rag import (
    RetrievalDocument,
    RetrievalHit,
)

from app.services.context_builder import (
    build_agent_context,
)


def _make_hit(
    *,
    document_id: str,
    source: str,
    score: float,
    text: str,
    metadata: dict | None = None,
) -> RetrievalHit:

    return RetrievalHit(
        document=(
            RetrievalDocument(
                id=document_id,
                source=source,
                text=text,
                metadata=(
                    metadata
                    or {}
                ),
            )
        ),
        score=score,
    )


def test_context_contains_provenance_backed_citations():

    hit = _make_hit(
        document_id="chunk-mcp-001",
        source="agentmesh-mcp",
        score=0.91,
        text=(
            "AgentMesh Runtime includes "
            "MCP Discovery Failure Backoff."
        ),
        metadata={
            "documentType":
                "agentmesh-demo",
            "chunkIndex":
                0,
            "start":
                0,
            "end":
                80,
        },
    )

    context = build_agent_context(
        task=(
            "Explain MCP Failure Backoff."
        ),
        memory_messages=[],
        retrieval_hits=[
            hit
        ],
    )

    assert (
        "[Retrieved Knowledge]"
        in context
    )

    assert (
        "[Evidence 1]"
        in context
    )

    assert (
        "[1] source=agentmesh-mcp; "
        "score=0.9100"
        in context
    )

    assert (
        "citation=[1]"
        in context
    )

    assert (
        "document_id=chunk-mcp-001"
        in context
    )

    assert (
        "document_type=agentmesh-demo"
        in context
    )

    assert (
        "chunk_index=0"
        in context
    )

    assert (
        "start=0"
        in context
    )

    assert (
        "end=80"
        in context
    )


def test_context_contains_citation_policy():

    hit = _make_hit(
        document_id="doc-1",
        source="source-1",
        score=0.80,
        text="Evidence one.",
    )

    context = build_agent_context(
        task="Answer from evidence.",
        memory_messages=[],
        retrieval_hits=[
            hit
        ],
    )

    assert (
        "[Citation Policy]"
        in context
    )

    assert (
        "available_citations=[1]"
        in context
    )

    assert (
        "Never invent, renumber, or guess "
        "citation labels."
        in context
    )

    assert (
        "Place a citation immediately after "
        "the claim it supports."
        in context
    )

    assert (
        "Conversation Memory"
        in context
    )

    assert (
        "evidence data"
        in context
    )


def test_context_preserves_citation_order():

    first = _make_hit(
        document_id="doc-a",
        source="source-a",
        score=0.90,
        text="First evidence.",
    )

    second = _make_hit(
        document_id="doc-b",
        source="source-b",
        score=0.70,
        text="Second evidence.",
    )

    context = build_agent_context(
        task="Use the evidence.",
        memory_messages=[],
        retrieval_hits=[
            first,
            second,
        ],
    )

    first_position = (
        context.index(
            "[Evidence 1]"
        )
    )

    second_position = (
        context.index(
            "[Evidence 2]"
        )
    )

    assert (
        first_position
        < second_position
    )

    assert (
        "available_citations=[1] [2]"
        in context
    )

    assert (
        "citation=[1]"
        in context
    )

    assert (
        "citation=[2]"
        in context
    )


def test_context_deduplicates_duplicate_document_citations():

    first = _make_hit(
        document_id="same-document",
        source="source-a",
        score=0.90,
        text="First occurrence.",
    )

    duplicate = _make_hit(
        document_id="same-document",
        source="source-a",
        score=0.60,
        text="Duplicate occurrence.",
    )

    context = build_agent_context(
        task="Use evidence.",
        memory_messages=[],
        retrieval_hits=[
            first,
            duplicate,
        ],
    )

    assert (
        context.count(
            "[Evidence 1]"
        )
        == 1
    )

    assert (
        "[Evidence 2]"
        not in context
    )

    assert (
        "available_citations=[1]"
        in context
    )

    assert (
        "First occurrence."
        in context
    )

    assert (
        "Duplicate occurrence."
        not in context
    )


def test_context_without_retrieval_has_no_citation_policy():

    context = build_agent_context(
        task="Hello",
        memory_messages=[],
        retrieval_hits=[],
    )

    assert (
        "[Retrieved Knowledge]"
        not in context
    )

    assert (
        "[Citation Policy]"
        not in context
    )

    assert (
        "available_citations="
        not in context
    )