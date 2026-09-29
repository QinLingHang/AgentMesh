from app.document_text_normalization import (
    normalize_document_text,
    normalize_pdf_pages,
)


def test_normalize_document_text_preserves_lexical_signals_and_code():
    text = (
        "\ufeffAPI_KEY\u200b = abc-123\u00a0\u00a0RRF@10\r\n\r\n"
        "```python\r\n"
        "value    =    'keep spacing'\r\n"
        "```\r\n"
    )

    normalized = normalize_document_text(text)

    assert "API_KEY = abc-123 RRF@10" in normalized
    assert "\u200b" not in normalized
    assert "value    =    'keep spacing'" in normalized


def test_normalize_pdf_pages_repairs_hyphenation_and_soft_line_wraps():
    pages = [
        "AgentMesh RAG\nThe retriev-\nal pipeline keeps lexical signals\nwithout rewriting identifiers.\n1",
    ]

    normalized = normalize_pdf_pages(pages)

    assert len(normalized) == 1
    assert "retrieval pipeline keeps lexical signals" in normalized[0]
    assert not normalized[0].endswith("\n1")


def test_normalize_pdf_pages_removes_repeated_headers_and_footers():
    pages = [
        "AgentMesh Internal 2026\nFirst page body.\nConfidential\n1 / 3",
        "AgentMesh Internal 2026\nSecond page body.\nConfidential\n2 / 3",
        "AgentMesh Internal 2026\nThird page body.\nConfidential\n3 / 3",
    ]

    normalized = normalize_pdf_pages(pages)

    assert normalized == [
        "First page body.",
        "Second page body.",
        "Third page body.",
    ]


def test_two_page_document_does_not_guess_repeated_headers():
    pages = [
        "Release Notes\nAlpha body.",
        "Release Notes\nBeta body.",
    ]

    normalized = normalize_pdf_pages(pages)

    assert normalized[0].startswith("Release Notes")
    assert normalized[1].startswith("Release Notes")
