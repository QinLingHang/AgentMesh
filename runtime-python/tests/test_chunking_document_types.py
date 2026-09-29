from app.document_text_normalization import normalize_document_text
from app.rag import chunk_text


def test_csv_rows_are_packed_instead_of_becoming_one_chunk_per_row():
    rows = ["id,name,status"] + [f"{i},item-{i},available" for i in range(1, 31)]
    text = "\n".join(rows)

    chunks = chunk_text(
        text=text,
        source="inventory.csv",
        metadata={"documentType": "csv"},
        chunk_size=240,
        overlap=40,
    )

    assert 1 < len(chunks) < len(rows)
    assert all(chunk.metadata["sourceDocumentType"] == "csv" for chunk in chunks)
    assert all(len(chunk.text) <= 240 for chunk in chunks)
    assert any("row" in chunk.metadata.get("blockTypes", []) for chunk in chunks)


def test_json_lines_are_context_packed_without_rewriting_source():
    text = "{\n" + ",\n".join(f'  \"key_{i}\": \"value_{i}\"' for i in range(30)) + "\n}"

    chunks = chunk_text(
        text=text,
        source="config.json",
        metadata={"documentType": "json"},
        chunk_size=220,
        overlap=30,
    )

    assert len(chunks) >= 2
    assert all(len(chunk.text) <= 220 for chunk in chunks)
    assert any("json" in chunk.metadata.get("blockTypes", []) for chunk in chunks)
    normalized = normalize_document_text(text)
    assert all(
        chunk.text == normalized[chunk.metadata["start"] : chunk.metadata["end"]]
        for chunk in chunks
    )


def test_pdf_line_blocks_pack_under_same_policy():
    text = "\n".join(
        [
            "Release Overview",
            "The runtime keeps evidence grounded.",
            "The retriever combines dense and lexical signals.",
            "The reranker improves final ordering.",
            "The citation layer preserves source provenance.",
        ]
        * 4
    )

    chunks = chunk_text(
        text=text,
        source="manual.pdf",
        metadata={"documentType": "pdf"},
        chunk_size=260,
        overlap=40,
    )

    assert chunks
    assert all(len(chunk.text) <= 260 for chunk in chunks)
    assert any("pdf_paragraph" in chunk.metadata.get("blockTypes", []) for chunk in chunks)


def test_markdown_heading_inside_fenced_code_is_not_treated_as_real_section():
    text = (
        "# Real\n\n"
        "```markdown\n"
        "# Not A Real Heading\n"
        "value = API_KEY\n"
        "```\n\n"
        "Body after the code block."
    )

    chunks = chunk_text(text=text, source="code.md", chunk_size=300, overlap=40)

    assert chunks
    all_paths = [
        path
        for chunk in chunks
        for path in chunk.metadata.get("headingPaths", [])
    ]
    assert any(path[-1] == "Real" for path in all_paths)
    assert all(path[-1] != "Not A Real Heading" for path in all_paths)
    assert any("# Not A Real Heading" in chunk.text for chunk in chunks)


def test_ordered_list_item_is_not_promoted_to_heading():
    text = "# Steps\n\n1. install package\n2. configure API_KEY\n3. restart service"

    chunks = chunk_text(text=text, source="steps.md", chunk_size=180, overlap=20)

    assert chunks
    paths = [path for chunk in chunks for path in chunk.metadata.get("headingPaths", [])]
    assert all("install package" not in path for path in paths)
    assert any("1. install package" in chunk.text for chunk in chunks)


def test_chinese_hierarchical_headings_are_preserved_as_structure():
    text = "第一章 总则\n\n这是总则内容。\n\n一、范围\n\n这里说明适用范围。"

    chunks = chunk_text(text=text, source="policy.txt", chunk_size=200, overlap=30)

    assert chunks
    assert chunks[0].metadata["chunkStrategy"] == "context_preserving_structure_v2"
    assert any(chunk.metadata.get("headingPaths") for chunk in chunks)
