import pytest

from app.rag import chunk_text


def test_structure_aware_chunking_keeps_legacy_boundary_free_overlap_contract():
    chunks = chunk_text(
        text="A" * 600,
        source="test-doc",
        metadata={"userId": 7},
        chunk_size=500,
        overlap=100,
    )

    assert len(chunks) == 2
    assert chunks[0].metadata["userId"] == 7
    assert chunks[1].metadata["start"] == 400
    assert chunks[0].id != chunks[1].id


def test_structure_aware_chunking_tracks_heading_path_and_metadata():
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
        chunk.metadata["chunkStrategy"] == "structure_aware_recursive_v1"
        for chunk in chunks
    )
    assert any(chunk.metadata.get("heading") == "Retrieval" for chunk in chunks)
    assert any(chunk.metadata.get("heading") == "Lexical" for chunk in chunks)
    assert any("API_KEY" in chunk.text for chunk in chunks)
    assert any("GPT-5" in chunk.text for chunk in chunks)
    assert any("ERR_429" in chunk.text for chunk in chunks)


def test_overlap_does_not_cross_identified_heading_sections():
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
        chunk for chunk in chunks if chunk.metadata.get("heading") == "Second"
    ]
    assert second_section
    assert all("alpha sentence" not in chunk.text for chunk in second_section)


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
