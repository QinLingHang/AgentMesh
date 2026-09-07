from app.rag.runtime import (
    RetrievalDocument,
    RetrievalHit,
)

from app.services.grounded_answer_guard import (
    guard_grounded_answer,
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


def test_guard_allows_clean_grounded_partial_answer():

    answer = (
        "The retrieved knowledge confirms that "
        "MCP Discovery Failure Backoff is a named "
        "capability of AgentMesh Runtime. "
        "The implementation and recovery details "
        "cannot be determined from the current "
        "knowledge base."
    )

    result = guard_grounded_answer(
        task=(
            "Explain MCP Failure Backoff "
            "and recovery."
        ),
        answer=answer,
        policy=(
            "grounded_partial_only"
        ),
        retrieval_hits=[
            _make_hit()
        ],
    )

    assert result.passed is True

    assert (
        result.action
        == "allow"
    )

    assert (
        result.answer
        == answer
    )

    assert (
        result.violations
        == ()
    )


def test_guard_replaces_speculative_example_with_safe_fallback():

    unsafe_answer = (
        "The knowledge confirms the capability, "
        "but does not describe its mechanism "
        "(e.g., exponential backoff parameters)."
    )

    result = guard_grounded_answer(
        task=(
            "Explain MCP Failure Backoff "
            "and recovery."
        ),
        answer=unsafe_answer,
        policy=(
            "grounded_partial_only"
        ),
        retrieval_hits=[
            _make_hit()
        ],
    )

    assert result.passed is False

    assert (
        result.action
        == "safe_fallback"
    )

    assert result.violations

    # Unsafe generated speculation must disappear.
    lowered = (
        result.answer
        .lower()
    )

    assert (
        "exponential"
        not in lowered
    )

    assert (
        "e.g."
        not in lowered
    )

    # Real retrieved evidence must be preserved.
    assert (
        "MCP Discovery Failure Backoff"
        in result.answer
    )

    assert (
        "agentmesh-mcp"
        in result.answer
    )

    assert (
        "cannot be determined"
        in lowered
    )


def test_guard_is_not_applied_to_other_policies():

    answer = (
        "Example answer with e.g. content."
    )

    result = guard_grounded_answer(
        task="General question.",
        answer=answer,
        policy="grounded_only",
        retrieval_hits=[],
    )

    assert result.passed is True

    assert (
        result.action
        == "not_applicable"
    )

    assert (
        result.answer
        == answer
    )


def test_guard_returns_safe_answer_when_no_evidence_exists():

    result = guard_grounded_answer(
        task=(
            "Explain unknown behavior."
        ),
        answer=(
            "It possibly uses something."
        ),
        policy=(
            "grounded_partial_only"
        ),
        retrieval_hits=[],
    )

    assert result.passed is False

    assert (
        result.action
        == "safe_fallback"
    )

    assert (
        "possibly"
        not in (
            result.answer
            .lower()
        )
    )

    assert (
        "does not contain sufficient evidence"
        in (
            result.answer
            .lower()
        )
    )


def test_guard_returns_chinese_safe_fallback_for_chinese_task():

    result = guard_grounded_answer(
        task=(
            "解释 AgentMesh 的 "
            "MCP Failure Backoff。"
        ),
        answer=(
            "可能使用某种机制，"
            "for example 某个实现。"
        ),
        policy=(
            "grounded_partial_only"
        ),
        retrieval_hits=[
            _make_hit()
        ],
    )

    assert result.passed is False

    assert (
        "当前知识库只能为该问题提供部分证据"
        in result.answer
    )

    assert (
        "MCP Discovery Failure Backoff"
        in result.answer
    )

    assert (
        "无法根据当前知识库得出"
        in result.answer
    )
def test_safe_fallback_filters_irrelevant_low_score_documents():

    relevant_hit = RetrievalHit(
        document=(
            RetrievalDocument(
                id="doc-mcp",
                text=(
                    "AgentMesh uses MCP for external "
                    "tool integration.\n"
                    "Runtime includes MCP Discovery "
                    "Failure Backoff."
                ),
                source="agentmesh-mcp",
                metadata={},
            )
        ),
        score=0.80,
    )

    irrelevant_hit = RetrievalHit(
        document=(
            RetrievalDocument(
                id="doc-deployment",
                text=(
                    "AgentMesh production deployment "
                    "uses Docker, Nginx and HTTPS."
                ),
                source="agentmesh-deployment",
                metadata={},
            )
        ),
        score=0.40,
    )

    result = guard_grounded_answer(
        task=(
            "Explain AgentMesh MCP Failure "
            "Backoff and recovery."
        ),
        answer=(
            "It may use e.g. exponential backoff."
        ),
        policy="grounded_partial_only",
        retrieval_hits=[
            relevant_hit,
            irrelevant_hit,
        ],
    )

    assert result.passed is False

    assert (
        result.action
        == "safe_fallback"
    )

    assert (
        "agentmesh-mcp"
        in result.answer
    )

    assert (
        "agentmesh-deployment"
        not in result.answer
    )

    assert (
        "Docker"
        not in result.answer
    )


def test_safe_fallback_extracts_only_relevant_document_segments():

    hit = RetrievalHit(
        document=(
            RetrievalDocument(
                id="doc-mcp",
                text=(
                    "AgentMesh uses MCP for external "
                    "tool integration.\n"
                    "Runtime includes MCP Discovery "
                    "Failure Backoff.\n"
                    "Tool Governance and Risk Level "
                    "are also supported.\n"
                    "Human-in-the-loop approval is "
                    "another platform capability."
                ),
                source="agentmesh-mcp",
                metadata={},
            )
        ),
        score=0.85,
    )

    result = guard_grounded_answer(
        task=(
            "Explain AgentMesh MCP Failure "
            "Backoff mechanism and recovery."
        ),
        answer=(
            "It uses e.g. some retry mechanism."
        ),
        policy="grounded_partial_only",
        retrieval_hits=[
            hit
        ],
    )

    assert (
        "MCP Discovery Failure Backoff"
        in result.answer
    )

    assert (
        "Tool Governance"
        not in result.answer
    )

    assert (
        "Risk Level"
        not in result.answer
    )

    assert (
        "Human-in-the-loop"
        not in result.answer
    )


def test_relevant_second_hit_can_survive_when_score_and_overlap_are_strong():

    first_hit = RetrievalHit(
        document=(
            RetrievalDocument(
                id="doc-1",
                text=(
                    "AgentMesh Runtime includes "
                    "MCP Discovery Failure Backoff."
                ),
                source="mcp-overview",
                metadata={},
            )
        ),
        score=0.90,
    )

    second_hit = RetrievalHit(
        document=(
            RetrievalDocument(
                id="doc-2",
                text=(
                    "MCP Failure Backoff recovery "
                    "documentation is incomplete."
                ),
                source="mcp-recovery",
                metadata={},
            )
        ),
        score=0.75,
    )

    result = guard_grounded_answer(
        task=(
            "Explain MCP Failure Backoff "
            "and recovery."
        ),
        answer=(
            "It may use e.g. an unknown strategy."
        ),
        policy="grounded_partial_only",
        retrieval_hits=[
            first_hit,
            second_hit,
        ],
    )

    assert (
        "mcp-overview"
        in result.answer
    )

    assert (
        "mcp-recovery"
        in result.answer
    )
def test_safe_fallback_preserves_original_provenance_citation_ids():

    first_hit = RetrievalHit(
        document=(
            RetrievalDocument(
                id="doc-1",
                source="source-1",
                text=(
                    "AgentMesh MCP Failure Backoff "
                    "is a Runtime capability."
                ),
                metadata={},
            )
        ),
        score=0.90,
    )

    # High score, but irrelevant to the current question.
    #
    # It owns citation [2] in the original evidence set.
    second_hit = RetrievalHit(
        document=(
            RetrievalDocument(
                id="doc-2",
                source="source-2",
                text=(
                    "AgentMesh production deployment "
                    "uses Docker and Nginx."
                ),
                metadata={},
            )
        ),
        score=0.85,
    )

    # This relevant evidence is citation [3].
    third_hit = RetrievalHit(
        document=(
            RetrievalDocument(
                id="doc-3",
                source="source-3",
                text=(
                    "MCP Failure Backoff recovery "
                    "documentation is incomplete."
                ),
                metadata={},
            )
        ),
        score=0.80,
    )

    result = guard_grounded_answer(
        task=(
            "Explain AgentMesh MCP Failure "
            "Backoff and recovery."
        ),
        answer=(
            "It may use e.g. an unknown "
            "retry strategy."
        ),
        policy=(
            "grounded_partial_only"
        ),
        retrieval_hits=[
            first_hit,
            second_hit,
            third_hit,
        ],
    )

    assert (
        result.action
        == "safe_fallback"
    )

    # Relevant first evidence keeps [1].
    assert (
        "[1] source=source-1"
        in result.answer
    )

    # doc-2 is removed by Evidence Selection.
    assert (
        "source=source-2"
        not in result.answer
    )

    # IMPORTANT:
    #
    # doc-3 was [3] before filtering,
    # therefore it must remain [3].
    assert (
        "[3] source=source-3"
        in result.answer
    )

    # It must never be locally renumbered.
    assert (
        "[2] source=source-3"
        not in result.answer
    )