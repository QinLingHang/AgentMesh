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


def test_engine_imports_citation_runtime_dependencies():

    source = _engine_source()

    assert (
        "build_evidence_provenance"
        in source
    )

    assert (
        "guard_answer_citations"
        in source
    )


def test_citation_guard_runs_before_memory_writeback():

    source = _engine_source()

    grounded_guard_position = (
        source.index(
            "# 8.1 Deterministic Grounded Answer Guard"
        )
    )

    citation_guard_position = (
        source.index(
            "# 8.2 Deterministic Citation Guard"
        )
    )

    memory_position = (
        source.index(
            "# 9. Conversation Memory Write-back"
        )
    )

    assert (
        grounded_guard_position
        < citation_guard_position
        < memory_position
    )


def test_runtime_citation_policy_is_explicit():

    source = _engine_source()

    citation_guard_position = (
        source.index(
            "# 8.2 Deterministic Citation Guard"
        )
    )

    memory_position = (
        source.index(
            "# 9. Conversation Memory Write-back"
        )
    )

    citation_block = source[
        citation_guard_position:
        memory_position
    ]

    assert (
        '"grounded_only"'
        in citation_block
    )

    assert (
        '"grounded_partial_only"'
        in citation_block
    )

    assert (
        "build_evidence_provenance("
        in citation_block
    )

    assert (
        "guard_answer_citations("
        in citation_block
    )

    assert (
        '== "grounded_only"'
        in citation_block
    )

    assert (
        '"Citation Guard"'
        in citation_block
    )
def test_guarded_answer_replaces_original_before_memory():

    source = _engine_source()

    citation_guard_position = (
        source.index(
            "# 8.2 Deterministic Citation Guard"
        )
    )

    memory_position = (
        source.index(
            "# 9. Conversation Memory Write-back"
        )
    )

    citation_block = source[
        citation_guard_position:
        memory_position
    ]

    assert (
        "citation_guard_result"
        in citation_block
    )

    assert (
        "answer = ("
        in citation_block
    )

    assert (
        "citation_guard_result"
        in citation_block
    )

    assert (
        ".answer"
        in citation_block
    )


def test_memory_runs_only_after_citation_guard_block():

    source = _engine_source()

    guard_call_position = (
        source.index(
            "guard_answer_citations("
        )
    )

    guarded_answer_position = (
        source.index(
            "citation_guard_result",
            guard_call_position,
        )
    )

    memory_position = (
        source.index(
            "# 9. Conversation Memory Write-back"
        )
    )

    assert (
        guard_call_position
        < guarded_answer_position
        < memory_position
    )