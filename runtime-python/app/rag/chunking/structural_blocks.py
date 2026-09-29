from __future__ import annotations

import re
from dataclasses import dataclass

from app.rag.chunking.contracts import StructuralBlock


_MARKDOWN_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_NUMBERED_HEADING_RE = re.compile(r"^(\d+(?:\.\d+){0,5})[.)、]?\s+(.+?)\s*$")
_CHINESE_CHAPTER_RE = re.compile(
    r"^第\s*([一二三四五六七八九十百千万0-9]+)\s*[章节篇部]\s*(.*)$"
)
_CHINESE_HEADING_RE = re.compile(r"^([一二三四五六七八九十百]+)[、.．]\s*(.+?)\s*$")
_MARKDOWN_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_LIST_RE = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)、]\s+|[一二三四五六七八九十百]+[、.)]\s*)")
_TABLE_RE = re.compile(r"^\s*\|.*\|\s*$")


@dataclass(frozen=True, slots=True)
class StructuralAnalysis:
    blocks: tuple[StructuralBlock, ...]
    has_structure: bool


def extract_structural_blocks(text: str, *, document_type: str = "") -> StructuralAnalysis:
    """Extract source-aligned blocks without turning every boundary into a chunk.

    Headings are recognized only outside fenced code. Ordinary prose uses blank
    lines as paragraph boundaries. PDF/CSV/JSON inputs are line-sensitive because
    their parsers already expose useful row/paragraph/object layout with newlines.
    The result never rewrites source text and therefore remains citation-safe.
    """
    if not text:
        return StructuralAnalysis(blocks=(), has_structure=False)

    document_type = document_type.strip().lower().lstrip(".")
    line_sensitive = document_type in {"pdf", "csv", "json"}

    blocks: list[StructuralBlock] = []
    heading_stack: list[str] = []
    section_number = 0
    current_section_id = "section-0"
    body_start: int | None = None
    body_end: int | None = None
    body_type = "paragraph"

    in_fence = False
    fence_token = ""
    offset = 0

    def flush_body() -> None:
        nonlocal body_start, body_end, body_type
        if body_start is None or body_end is None:
            body_start = None
            body_end = None
            body_type = "paragraph"
            return
        start, end = _trim_span(text, body_start, body_end)
        if end > start:
            blocks.append(
                StructuralBlock(
                    start=start,
                    end=end,
                    block_type=body_type,
                    heading_path=tuple(heading_stack),
                    section_id=current_section_id,
                    starts_heading=False,
                )
            )
        body_start = None
        body_end = None
        body_type = "paragraph"

    for line_with_newline in text.splitlines(keepends=True):
        line_end = offset + len(line_with_newline)
        content_end = line_end
        while content_end > offset and text[content_end - 1] in "\r\n":
            content_end -= 1
        raw_line = text[offset:content_end]
        stripped = raw_line.strip()

        fence_match = _MARKDOWN_FENCE_RE.match(raw_line)
        if fence_match:
            token = fence_match.group(1)
            if not in_fence:
                in_fence = True
                fence_token = token
            elif token == fence_token:
                in_fence = False
                fence_token = ""

        heading_info = None if in_fence or fence_match else _heading_info(raw_line)
        if heading_info is not None:
            flush_body()
            level, title = heading_info
            heading_stack = _updated_heading_stack(heading_stack, level=level, title=title)
            section_number += 1
            current_section_id = f"section-{section_number}"
            start, end = _trim_span(text, offset, content_end)
            if end > start:
                blocks.append(
                    StructuralBlock(
                        start=start,
                        end=end,
                        block_type="heading",
                        heading_path=tuple(heading_stack),
                        section_id=current_section_id,
                        starts_heading=True,
                    )
                )
            offset = line_end
            continue

        if not stripped and not in_fence:
            flush_body()
            offset = line_end
            continue

        current_type = _body_type(raw_line, document_type=document_type)
        if line_sensitive and body_start is not None and not in_fence:
            flush_body()

        if body_start is None:
            body_start = offset
            body_end = content_end
            body_type = current_type
        else:
            body_end = content_end
            if body_type != current_type:
                body_type = "mixed"

        offset = line_end

    # splitlines(keepends=True) returns the final line as well, but the empty-text
    # and newline-only cases still need the same defensive flush behavior.
    flush_body()

    # A single unheaded block has no useful structural boundary. Falling back to
    # the legacy fixed window keeps long boundary-free text deterministic.
    has_heading = any(block.starts_heading for block in blocks)
    has_structure = has_heading or len(blocks) > 1
    return StructuralAnalysis(blocks=tuple(blocks), has_structure=has_structure)


def _heading_info(line: str) -> tuple[int, str] | None:
    stripped = line.strip()
    if not stripped or len(stripped) > 120:
        return None

    markdown = _MARKDOWN_HEADING_RE.match(stripped)
    if markdown:
        return len(markdown.group(1)), markdown.group(2).strip()

    chapter = _CHINESE_CHAPTER_RE.match(stripped)
    if chapter:
        return 1, stripped

    numbered = _NUMBERED_HEADING_RE.match(stripped)
    if numbered and not stripped.endswith(("。", "！", "？", ".", "!", "?")):
        number = numbered.group(1)
        raw_prefix = stripped[: numbered.start(2)].rstrip()
        # Do not turn ordinary ordered-list items ("1. install") into headings.
        if "." in number or raw_prefix == number:
            level = min(6, number.count(".") + 1)
            return level, f"{number} {numbered.group(2).strip()}".strip()

    chinese = _CHINESE_HEADING_RE.match(stripped)
    if chinese and not stripped.endswith(("。", "！", "？")):
        return 2, stripped
    return None


def _updated_heading_stack(heading_stack: list[str], *, level: int, title: str) -> list[str]:
    level = max(1, min(6, level))
    updated = heading_stack[: level - 1]
    while len(updated) < level - 1:
        updated.append("")
    updated.append(title)
    return [item for item in updated if item]


def _body_type(line: str, *, document_type: str) -> str:
    stripped = line.strip()
    if document_type == "csv":
        return "row"
    if document_type == "json":
        return "json"
    if _TABLE_RE.match(stripped):
        return "table"
    if _LIST_RE.match(stripped):
        return "list"
    if document_type == "pdf":
        return "pdf_paragraph"
    if _MARKDOWN_FENCE_RE.match(stripped):
        return "code"
    return "paragraph"


def _trim_span(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end
