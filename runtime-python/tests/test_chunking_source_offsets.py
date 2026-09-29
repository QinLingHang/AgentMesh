from app.document_text_normalization import normalize_document_text
from app.rag import chunk_text


def test_every_non_whitespace_source_character_is_covered_by_at_least_one_chunk():
    raw = (
        "# One\n\n"
        + "Alpha semantic context. " * 20
        + "\n\n# Two\n\n"
        + "Beta relational context. " * 20
    )
    normalized = normalize_document_text(raw)
    chunks = chunk_text(text=raw, source="coverage.md", chunk_size=180, overlap=40)

    covered: set[int] = set()
    for chunk in chunks:
        start = chunk.metadata["start"]
        end = chunk.metadata["end"]
        covered.update(range(start, end))
        assert chunk.text == normalized[start:end]
        assert end > start
        assert len(chunk.text) <= 180

    missing = [i for i, char in enumerate(normalized) if not char.isspace() and i not in covered]
    assert missing == []


def test_offsets_are_monotonic_and_overlap_metadata_matches_actual_spans():
    text = "# Section\n\n" + "Sentence number one. Sentence number two. " * 20
    chunks = chunk_text(text=text, source="ordered.md", chunk_size=160, overlap=35)

    assert chunks
    for previous, current in zip(chunks, chunks[1:]):
        assert current.metadata["start"] > previous.metadata["start"]
        assert current.metadata["end"] > previous.metadata["end"]
        expected = max(0, previous.metadata["end"] - current.metadata["start"])
        assert current.metadata["overlapChars"] == expected


def test_base_metadata_is_copied_not_mutated():
    base = {"documentId": "doc-1", "documentType": "md", "custom": {"x": 1}}
    before = dict(base)

    chunks = chunk_text(
        text="# A\n\nOne.\n\n# B\n\nTwo.",
        source="metadata.md",
        metadata=base,
        chunk_size=80,
        overlap=10,
    )

    assert chunks
    assert base == before
    assert "chunkIndex" not in base
    assert all(chunk.metadata["documentId"] == "doc-1" for chunk in chunks)


def test_empty_and_whitespace_only_input_return_no_chunks():
    assert chunk_text(text="", source="empty.txt") == []
    assert chunk_text(text=" \n\t\r\n ", source="blank.txt") == []


def test_pathological_long_token_makes_progress_and_respects_hard_max():
    text = "# Token\n\n" + ("X" * 1400)
    chunks = chunk_text(text=text, source="token.md", chunk_size=500, overlap=100)

    assert len(chunks) >= 3
    assert all(0 < len(chunk.text) <= 500 for chunk in chunks)
    assert all(
        current.metadata["start"] > previous.metadata["start"]
        for previous, current in zip(chunks, chunks[1:])
    )

def test_fixed_fallback_near_max_overlap_never_repeats_visible_start():
    text = ("alpha  beta\n" * 120) + "omega"
    chunks = chunk_text(
        text=text,
        source="near-max-overlap.txt",
        chunk_size=54,
        overlap=53,
    )

    assert chunks
    starts = [chunk.metadata["start"] for chunk in chunks]
    assert all(current > previous for previous, current in zip(starts, starts[1:]))
    assert len({(chunk.metadata["start"], chunk.metadata["end"]) for chunk in chunks}) == len(chunks)
