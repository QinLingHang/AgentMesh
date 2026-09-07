from app.rag.runtime import (
    RetrievalDocument,
    RetrievalHit,
)

from app.services.context_builder import (
    build_agent_context,
)


def _make_hit() -> RetrievalHit:
    return RetrievalHit(
        document=(
            RetrievalDocument(
                id="doc-1",
                text=(
                    "AgentMesh Runtime includes "
                    "MCP Discovery Failure Backoff."
                ),
                source="agentmesh-mcp",
                metadata={},
            )
        ),
        score=0.85,
    )


def test_context_builder_injects_grounding_guard_for_insufficient_evidence():

    context = build_agent_context(
        task=(
            "Explain MCP Failure Backoff "
            "and recovery."
        ),
        memory_messages=[],
        retrieval_hits=[
            _make_hit()
        ],
        grounding_sufficient=False,
        grounding_reason=(
            "The evidence mentions the "
            "capability but does not explain "
            "retry or recovery behavior."
        ),
        grounding_stopped_reason=(
            "max_rounds_reached"
        ),
    )

    assert (
        "[RAG Grounding Status]"
        in context
    )

    assert (
        "status=insufficient"
        in context
    )

    assert (
        "max_rounds_reached"
        in context
    )

    assert (
        "does not explain retry or recovery behavior"
        in context
    )

    assert (
        "Do not infer, invent, or speculate about"
        in context
    )

    # Partial evidence must still be preserved.
    assert (
        "[Retrieved Knowledge]"
        in context
    )

    assert (
        "MCP Discovery Failure Backoff"
        in context
    )
    assert (
    "answer_policy=grounded_partial_only"
    in context
    )

    assert (
        "Do not introduce hypothetical technical"
        in context
    )

    assert (
        "even as examples"
        in context
    )

    assert (
        "Do not fill evidence gaps using general"
        in context
    )

    assert (
        "'e.g.'"
        in context
    )


def test_context_builder_injects_guard_even_when_no_hits_exist():

    context = build_agent_context(
        task="Find unknown knowledge.",
        memory_messages=[],
        retrieval_hits=[],
        grounding_sufficient=False,
        grounding_reason=(
            "No retrieval evidence."
        ),
        grounding_stopped_reason=(
            "max_rounds_reached"
        ),
    )

    assert (
        "[RAG Grounding Status]"
        in context
    )

    assert (
        "status=insufficient"
        in context
    )

    assert (
        "No retrieval evidence."
        in context
    )

    assert (
        "[Retrieved Knowledge]"
        not in context
    )


def test_context_builder_does_not_add_insufficiency_guard_when_sufficient():

    context = build_agent_context(
        task="Explain AgentMesh.",
        memory_messages=[],
        retrieval_hits=[
            _make_hit()
        ],
        grounding_sufficient=True,
        grounding_reason=(
            "Evidence is sufficient."
        ),
        grounding_stopped_reason=(
            "evidence_sufficient"
        ),
    )

    assert (
        "[RAG Grounding Status]"
        not in context
    )

    assert (
        "[Retrieved Knowledge]"
        in context
    )
def test_grounding_policy_explicitly_blocks_speculative_examples():

    context = build_agent_context(
        task=(
            "Explain MCP Failure Backoff "
            "and recovery."
        ),
        memory_messages=[],
        retrieval_hits=[
            _make_hit()
        ],
        grounding_sufficient=False,
        grounding_reason=(
            "The available evidence does not "
            "describe the mechanism or recovery."
        ),
        grounding_stopped_reason=(
            "max_rounds_reached"
        ),
    )

    assert (
        "answer_policy=grounded_partial_only"
        in context
    )

    assert (
        "Do not introduce hypothetical technical "
        "mechanisms"
        in context
    )

    assert (
        "even as examples"
        in context
    )

    assert (
        "Do not use phrases such as 'for example'"
        in context
    )

    assert (
        "Do not fill evidence gaps using general "
        "domain knowledge"
        in context
    )

    assert (
        "Keep the answer concise and evidence-focused"
        in context
    )