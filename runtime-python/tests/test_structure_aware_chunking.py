import pytest

from app.document_text_normalization import normalize_document_text
from app.rag import chunk_text


def test_boundary_free_text_keeps_legacy_fixed_window_overlap_contract():
    chunks = chunk_text(
        text="A" * 600,
        source="test-doc",
        metadata={"userId": 7},
        chunk_size=500,
        overlap=100,
    )

    assert len(chunks) == 2
    assert chunks[0].metadata["userId"] == 7
    assert chunks[0].metadata["chunkStrategy"] == "fixed_window_fallback_v1"
    assert chunks[1].metadata["start"] == 400
    assert chunks[1].metadata["overlapChars"] == 100
    assert chunks[0].id != chunks[1].id


def test_context_preserving_chunking_tracks_heading_paths_and_metadata():
    text = (
        "# Retrieval\n\n"
        + "Dense retrieval captures semantic similarity. " * 12
        + "\n\n## Lexical\n\n"
        + "BM25 protects API_KEY, GPT-5 and ERR_429 lexical signals. " * 8
    )

    chunks = chunk_text(
        text=text,
        source="rag.md",
        chunk_size=220,
        overlap=40,
    )

    assert len(chunks) >= 3
    assert all(len(chunk.text) <= 220 for chunk in chunks)
    assert all(
        chunk.metadata["chunkStrategy"] == "context_preserving_structure_v2"
        for chunk in chunks
    )
    assert any(chunk.metadata.get("heading") == "Retrieval" for chunk in chunks)
    assert any(
        "Lexical" in path
        for chunk in chunks
        for path in chunk.metadata.get("headingPaths", [])
    )
    assert any("API_KEY" in chunk.text for chunk in chunks)
    assert any("GPT-5" in chunk.text for chunk in chunks)
    assert any("ERR_429" in chunk.text for chunk in chunks)


def test_overlap_from_oversized_split_does_not_cross_large_heading_sections():
    text = (
        "# First\n\n"
        + "alpha sentence. " * 20
        + "\n\n# Second\n\n"
        + "beta sentence. " * 20
    )

    chunks = chunk_text(
        text=text,
        source="sections.md",
        chunk_size=120,
        overlap=30,
    )

    second_section = [
        chunk
        for chunk in chunks
        if any(
            path and path[-1] == "Second"
            for path in chunk.metadata.get("headingPaths", [])
        )
    ]
    assert second_section
    assert all("alpha sentence" not in chunk.text for chunk in second_section)


def test_small_sections_are_packed_across_heading_boundaries():
    text = (
        "# Alpha\n\nAlpha has a short but useful fact.\n\n"
        "# Beta\n\nBeta adds another compact fact.\n\n"
        "# Gamma\n\nGamma finishes the related explanation."
    )

    chunks = chunk_text(text=text, source="small-sections.md", chunk_size=500, overlap=100)

    assert len(chunks) == 1
    assert chunks[0].metadata["containsMultipleSections"] is True
    assert len(chunks[0].metadata["sectionIds"]) == 3
    assert "Alpha has" in chunks[0].text
    assert "Gamma finishes" in chunks[0].text


def test_consecutive_headings_are_kept_with_following_body():
    text = "# Guide\n\n## Windows\n\n### Install\n\nRun the installer and verify the checksum."

    chunks = chunk_text(text=text, source="guide.md", chunk_size=180, overlap=30)

    assert chunks
    assert all(not chunk.text.rstrip().endswith(("# Guide", "## Windows", "### Install")) for chunk in chunks)
    assert any("### Install" in chunk.text and "Run the installer" in chunk.text for chunk in chunks)


def test_structured_oversized_region_avoids_tiny_terminal_fragment_when_possible():
    body = "Sentence with meaningful context and identifiers API_KEY. " * 14
    text = f"# Long Section\n\n{body}"

    chunks = chunk_text(text=text, source="long.md", chunk_size=500, overlap=100)

    assert len(chunks) >= 2
    assert all(len(chunk.text) <= 500 for chunk in chunks)
    assert all(len(chunk.text) >= 200 for chunk in chunks)
    assert any(chunk.metadata["overlapChars"] > 0 for chunk in chunks[1:])


def test_chunk_text_is_always_exact_normalized_source_span():
    raw = "# Title\r\n\r\nAlpha\u00a0\u00a0API_KEY.\r\n\r\n## Child\r\n\r\nBeta ERR_429."
    normalized = normalize_document_text(raw)

    chunks = chunk_text(text=raw, source="offsets.md", chunk_size=80, overlap=20)

    assert chunks
    for chunk in chunks:
        start = chunk.metadata["start"]
        end = chunk.metadata["end"]
        assert chunk.text == normalized[start:end]


def test_chunk_ids_are_deterministic_for_same_normalized_input():
    first = chunk_text(
        text="Hello\u00a0\u00a0world.\r\n" * 40,
        source="stable.txt",
        chunk_size=120,
        overlap=20,
    )
    second = chunk_text(
        text="Hello  world.\n" * 40,
        source="stable.txt",
        chunk_size=120,
        overlap=20,
    )

    assert [chunk.id for chunk in first] == [chunk.id for chunk in second]


@pytest.mark.parametrize(
    ("chunk_size", "overlap", "message"),
    [
        (0, 0, "chunk_size must be > 0"),
        (100, -1, "overlap must be >= 0"),
        (100, 100, "overlap must be smaller than chunk_size"),
        (100, 101, "overlap must be smaller than chunk_size"),
    ],
)
def test_chunking_rejects_invalid_config(chunk_size, overlap, message):
    with pytest.raises(ValueError, match=message):
        chunk_text(
            text="content",
            source="invalid.txt",
            chunk_size=chunk_size,
            overlap=overlap,
        )
