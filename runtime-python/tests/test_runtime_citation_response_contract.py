from pathlib import Path


ENGINE_PATH = (
    Path(__file__)
    .resolve()
    .parents[1]
    / "app"
    / "services"
    / "engine.py"
)


def _engine_source() -> str:

    return ENGINE_PATH.read_text(
        encoding="utf-8"
    )


def test_engine_imports_runtime_citation_projection():

    source = _engine_source()

    assert (
        "RuntimeCitation"
        in source
    )

    assert (
        "project_used_citations"
        in source
    )


def test_runtime_citations_start_empty():

    source = _engine_source()

    assert (
        "runtime_citations: list["
        in source
    )

    assert (
        "RuntimeCitation"
        in source
    )

    assert (
        "] = []"
        in source
    )


def test_projection_runs_after_guard_and_before_memory():

    source = _engine_source()

    citation_guard_position = (
        source.index(
            "guard_answer_citations("
        )
    )

    guard_passed_position = (
        source.index(
            "citation_guard_result",
            citation_guard_position,
        )
    )

    passed_check_position = (
        source.index(
            ".passed",
            guard_passed_position,
        )
    )

    projection_position = (
        source.index(
            "project_used_citations("
        )
    )

    memory_position = (
        source.index(
            "# 9. Conversation Memory Write-back"
        )
    )

    # --------------------------------------------------------
    # Required runtime order:
    #
    # Citation Guard
    #     ↓
    # citation_guard_result.passed
    #     ↓
    # Citation Projection
    #     ↓
    # Memory Write-back
    # --------------------------------------------------------

    assert (
        citation_guard_position
        < passed_check_position
        < projection_position
        < memory_position
    )

    integration_block = source[
        citation_guard_position:
        memory_position
    ]

    assert (
        "citation_guard_result"
        in integration_block
    )

    assert (
        ".passed"
        in integration_block
    )

    assert (
        "project_used_citations("
        in integration_block
    )

    assert (
        "Citation Provenance "
        in integration_block
    )

    assert (
        "Projected"
        in integration_block
    )


def test_final_completed_response_exposes_runtime_citations():

    source = _engine_source()

    # Validate behavior-bearing structure, not a numbered comment marker.
    # Numbered comments legitimately move as the runtime grows.
    response_position = source.rfind("return RuntimeResponse(")
    assert response_position >= 0

    response_section = source[response_position:]

    assert "RuntimeResponse(" in response_section
    assert "answer=(" in response_section
    assert "citations=(" in response_section
    assert "runtime_citations" in response_section
    assert "scorecard=scorecard" in response_section
