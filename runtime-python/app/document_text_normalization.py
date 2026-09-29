from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from collections.abc import Sequence


_ZERO_WIDTH_TRANSLATION = str.maketrans(
    {
        "\ufeff": "",
        "\u200b": "",
        "\u200c": "",
        "\u200d": "",
        "\u2060": "",
        "\u00ad": "",
        "\u00a0": " ",
        "\u202f": " ",
        "\u3000": " ",
    }
)
_HORIZONTAL_SPACE_RE = re.compile(r"[ \t\v\f]+")
_EXCESS_BLANK_LINES_RE = re.compile(r"\n{3,}")
_PAGE_NUMBER_RE = re.compile(
    r"^(?:page\s*)?\d+(?:\s*(?:/|of)\s*\d+)?$|^第\s*\d+\s*页(?:\s*/\s*共?\s*\d+\s*页)?$",
    re.IGNORECASE,
)
_MARKDOWN_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_MARKDOWN_HEADING_RE = re.compile(r"^\s*#{1,6}\s+\S")
_LIST_RE = re.compile(
    r"^\s*(?:[-*+]\s+|\d+[.)、]\s+|[一二三四五六七八九十百]+[、.)]\s*)"
)
_TABLE_RE = re.compile(r"^\s*\|.*\|\s*$")
_HYPHENATED_LINE_RE = re.compile(r"([A-Za-z]{2,})-\n([a-z][A-Za-z]{1,})")
_TRAILING_SENTENCE_RE = re.compile(r"[。！？!?；;：:]$|(?<!\b[A-Z])\.$")
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_DIGIT_RUN_RE = re.compile(r"\d+")


def normalize_document_text(text: str) -> str:
    """Normalize searchable text without destroying lexical signals or code.

    The normalizer deliberately preserves identifiers, punctuation, markdown headings,
    URLs and fenced-code indentation. It removes only transport/layout noise that is
    unlikely to carry retrieval meaning.
    """
    if not isinstance(text, str):
        raise TypeError("text must be a string")

    text = unicodedata.normalize("NFC", text)
    text = text.translate(_ZERO_WIDTH_TRANSLATION)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "".join(
        character
        for character in text
        if character in {"\n", "\t"}
        or not unicodedata.category(character).startswith("C")
    )

    normalized_lines: list[str] = []
    in_fence = False
    fence_token = ""

    for raw_line in text.split("\n"):
        fence_match = _MARKDOWN_FENCE_RE.match(raw_line)
        if fence_match:
            token = fence_match.group(1)
            if not in_fence:
                in_fence = True
                fence_token = token
            elif token == fence_token:
                in_fence = False
                fence_token = ""
            normalized_lines.append(raw_line.rstrip())
            continue

        if in_fence:
            normalized_lines.append(raw_line.rstrip())
            continue

        line = _HORIZONTAL_SPACE_RE.sub(" ", raw_line).strip()
        normalized_lines.append(line)

    normalized = "\n".join(normalized_lines)
    normalized = _EXCESS_BLANK_LINES_RE.sub("\n\n", normalized)
    return normalized.strip()


def normalize_pdf_pages(pages: Sequence[str]) -> list[str]:
    """Normalize PDF text page-by-page while retaining page boundaries.

    This removes obvious page-number noise and repeated headers/footers for documents
    with at least three pages, then repairs common PDF line-wrap and hyphenation noise.
    It intentionally does not attempt OCR or layout reconstruction.
    """
    prepared = [normalize_document_text(page or "") for page in pages]
    if not prepared:
        return []

    repeated_edges = _repeated_pdf_edge_fingerprints(prepared)
    result: list[str] = []

    for page in prepared:
        lines = page.splitlines()
        kept: list[str] = []
        nonempty_positions = [index for index, line in enumerate(lines) if line.strip()]
        edge_positions = set(nonempty_positions[:2] + nonempty_positions[-2:])

        for index, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                kept.append("")
                continue
            if _PAGE_NUMBER_RE.fullmatch(stripped):
                continue
            if index in edge_positions and _edge_fingerprint(stripped) in repeated_edges:
                continue
            kept.append(line)

        repaired = _repair_pdf_line_wraps("\n".join(kept))
        result.append(normalize_document_text(repaired))

    return result


def _repeated_pdf_edge_fingerprints(pages: Sequence[str]) -> set[str]:
    if len(pages) < 3:
        return set()

    counts: Counter[str] = Counter()
    for page in pages:
        lines = [line.strip() for line in page.splitlines() if line.strip()]
        page_candidates: set[str] = set()
        for line in lines[:2] + lines[-2:]:
            if len(line) > 120 or _PAGE_NUMBER_RE.fullmatch(line):
                continue
            fingerprint = _edge_fingerprint(line)
            if fingerprint:
                page_candidates.add(fingerprint)
        counts.update(page_candidates)

    threshold = max(3, math.ceil(len(pages) * 0.6))
    return {fingerprint for fingerprint, count in counts.items() if count >= threshold}


def _edge_fingerprint(line: str) -> str:
    collapsed = _HORIZONTAL_SPACE_RE.sub(" ", line).strip().casefold()
    collapsed = _DIGIT_RUN_RE.sub("<n>", collapsed)
    return collapsed


def _repair_pdf_line_wraps(text: str) -> str:
    text = _HYPHENATED_LINE_RE.sub(r"\1\2", text)
    lines = text.splitlines()
    if not lines:
        return ""

    paragraphs: list[str] = []
    current = ""

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            if current:
                paragraphs.append(current)
                current = ""
            if paragraphs and paragraphs[-1] != "":
                paragraphs.append("")
            continue

        if not current:
            current = line
            continue

        if _should_join_pdf_lines(current, line):
            separator = "" if _cjk_boundary(current, line) else " "
            current = f"{current}{separator}{line}"
        else:
            paragraphs.append(current)
            current = line

    if current:
        paragraphs.append(current)

    while paragraphs and paragraphs[-1] == "":
        paragraphs.pop()
    return "\n".join(paragraphs)


def _should_join_pdf_lines(previous: str, current: str) -> bool:
    if _looks_structural(previous) or _looks_structural(current):
        return False
    if _TRAILING_SENTENCE_RE.search(previous):
        return False
    if _looks_like_short_title(previous, current):
        return False
    return True


def _looks_structural(line: str) -> bool:
    return bool(
        _MARKDOWN_HEADING_RE.match(line)
        or _LIST_RE.match(line)
        or _TABLE_RE.match(line)
    )


def _looks_like_short_title(previous: str, current: str) -> bool:
    if len(previous) > 40:
        return False
    if len(current) <= len(previous):
        return False
    if previous.endswith((",", "，", "、", "-", "—")):
        return False
    return True


def _cjk_boundary(previous: str, current: str) -> bool:
    return bool(
        previous
        and current
        and _CJK_RE.fullmatch(previous[-1])
        and _CJK_RE.fullmatch(current[0])
    )
