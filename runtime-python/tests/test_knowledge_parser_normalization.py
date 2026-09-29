import pytest

from app.knowledge.parser import parse_document_bytes


def test_text_parser_normalizes_encoding_noise_without_erasing_identifiers():
    text = "\ufeffAgentMesh\u00a0\u00a0API_KEY\u200b = ERR_429\r\n\r\nRRF@10"

    parsed = parse_document_bytes(
        extension="txt",
        content=text.encode("utf-8"),
    )

    assert parsed == "AgentMesh API_KEY = ERR_429\n\nRRF@10"


def test_markdown_parser_preserves_heading_structure():
    parsed = parse_document_bytes(
        extension="md",
        content=b"# Retrieval\n\n## BM25\n\nExact identifiers stay searchable.\n",
    )

    assert parsed.startswith("# Retrieval")
    assert "## BM25" in parsed


def test_invalid_json_falls_back_to_text_instead_of_dropping_content():
    parsed = parse_document_bytes(
        extension="json",
        content=b'{"broken": true',
    )

    assert parsed == '{"broken": true'


def test_empty_and_unsupported_documents_fail_explicitly():
    with pytest.raises(ValueError, match="knowledge file is empty"):
        parse_document_bytes(extension="txt", content=b"")

    with pytest.raises(ValueError, match="unsupported knowledge extension"):
        parse_document_bytes(extension="xlsx", content=b"not-empty")
