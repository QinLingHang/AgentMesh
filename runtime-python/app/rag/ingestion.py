from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

from app.document_text_normalization import normalize_document_text
from app.rag.runtime import RetrievalDocument


_MARKDOWN_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_NUMBERED_HEADING_RE = re.compile(
    r"^(\d+(?:\.\d+){0,5})[.)、]?\s+(.+?)\s*$"
)
_CHINESE_CHAPTER_RE = re.compile(
    r"^第\s*([一二三四五六七八九十百千万0-9]+)\s*[章节篇部]\s*(.*)$"
)
_CHINESE_HEADING_RE = re.compile(
    r"^([一二三四五六七八九十百]+)[、.．]\s*(.+?)\s*$"
)
_SENTENCE_END_RE = re.compile(r"[。！？!?；;]\s*|(?<!\b[A-Z])\.\s+")


@dataclass(frozen=True, slots=True)
class _Section:
    start: int
    end: int
    heading_path: tuple[str, ...]


def chunk_text(
    *,
    text: str,
    source: str,
    metadata: dict[str, Any] | None = None,
    chunk_size: int = 500,
    overlap: int = 100,
) -> list[RetrievalDocument]:
    """Split text into deterministic, structure-aware retrieval chunks.

    The public contract stays backward compatible with the original fixed-window
    chunker. The implementation now prefers document/paragraph/sentence boundaries,
    never crosses an identified heading section for overlap, and falls back to a
    fixed character window when no usable boundary exists.

    ``start`` and ``end`` offsets refer to the normalized text consumed here.
    """
    _validate_chunking_config(chunk_size=chunk_size, overlap=overlap)

    normalized = normalize_document_text(text)
    if not normalized:
        return []

    base_metadata = dict(metadata or {})
    spans: list[tuple[int, int, tuple[str, ...]]] = []

    for section in _section_spans(normalized):
        spans.extend(
            (start, end, section.heading_path)
            for start, end in _chunk_section(
                normalized,
                section_start=section.start,
                section_end=section.end,
                chunk_size=chunk_size,
                overlap=overlap,
            )
        )

    chunks: list[RetrievalDocument] = []
    for index, (raw_start, raw_end, heading_path) in enumerate(spans):
        start, end = _trim_span(normalized, raw_start, raw_end)
        if end <= start:
            continue

        chunk = normalized[start:end]
        chunk_metadata: dict[str, Any] = {
            **base_metadata,
            "chunkIndex": index,
            "start": start,
            "end": end,
            "chunkLength": len(chunk),
            "chunkStrategy": "structure_aware_recursive_v1",
        }
        if heading_path:
            chunk_metadata["heading"] = heading_path[-1]
            chunk_metadata["headingPath"] = list(heading_path)

        chunks.append(
            RetrievalDocument(
                id=_chunk_id(source=source, index=index, text=chunk),
                text=chunk,
                source=source,
                metadata=chunk_metadata,
            )
        )

    return chunks


def _validate_chunking_config(*, chunk_size: int, overlap: int) -> None:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be > 0")
    if overlap < 0:
        raise ValueError("overlap must be >= 0")
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")


def _section_spans(text: str) -> list[_Section]:
    headings: list[tuple[int, int, str]] = []
    offset = 0

    for line_with_newline in text.splitlines(keepends=True):
        line = line_with_newline.rstrip("\r\n")
        info = _heading_info(line)
        if info is not None:
            level, title = info
            headings.append((offset, level, title))
        offset += len(line_with_newline)

    # ``splitlines(keepends=True)`` omits a synthetic trailing line; headings still
    # have correct offsets, and a heading-free document remains a single section.
    if not headings:
        return [_Section(start=0, end=len(text), heading_path=())]

    sections: list[_Section] = []
    heading_stack: list[str] = []
    cursor = 0

    for index, (heading_start, level, title) in enumerate(headings):
        if heading_start > cursor:
            sections.append(
                _Section(
                    start=cursor,
                    end=heading_start,
                    heading_path=tuple(heading_stack),
                )
            )

        heading_stack = _updated_heading_stack(heading_stack, level=level, title=title)
        next_start = headings[index + 1][0] if index + 1 < len(headings) else len(text)
        sections.append(
            _Section(
                start=heading_start,
                end=next_start,
                heading_path=tuple(heading_stack),
            )
        )
        cursor = next_start

    return [section for section in sections if section.end > section.start]


def _heading_info(line: str) -> tuple[int, str] | None:
    stripped = line.strip()
    if not stripped or len(stripped) > 120:
        return None

    markdown = _MARKDOWN_HEADING_RE.match(stripped)
    if markdown:
        return len(markdown.group(1)), markdown.group(2).strip()

    chapter = _CHINESE_CHAPTER_RE.match(stripped)
    if chapter:
        title = stripped
        return 1, title

    numbered = _NUMBERED_HEADING_RE.match(stripped)
    if numbered and not stripped.endswith(("。", "！", "？", ".", "!", "?")):
        number = numbered.group(1)
        raw_prefix = stripped[: numbered.start(2)].rstrip()
        # Avoid treating ordinary ordered-list items such as ``1. install`` as
        # top-level sections. Hierarchical numbering (1.1/1.2) and unpunctuated
        # forms such as ``1 Introduction`` remain eligible headings.
        if "." in number or raw_prefix == number:
            title = numbered.group(2).strip()
            level = min(6, number.count(".") + 1)
            return level, f"{number} {title}".strip()

    chinese = _CHINESE_HEADING_RE.match(stripped)
    if chinese and not stripped.endswith(("。", "！", "？")):
        return 2, stripped

    return None


def _updated_heading_stack(
    heading_stack: list[str],
    *,
    level: int,
    title: str,
) -> list[str]:
    level = max(1, min(6, level))
    updated = heading_stack[: level - 1]
    while len(updated) < level - 1:
        updated.append("")
    updated.append(title)
    return [item for item in updated if item]


def _chunk_section(
    text: str,
    *,
    section_start: int,
    section_end: int,
    chunk_size: int,
    overlap: int,
) -> list[tuple[int, int]]:
    start = _skip_whitespace_forward(text, section_start, section_end)
    result: list[tuple[int, int]] = []

    while start < section_end:
        target_end = min(section_end, start + chunk_size)
        if target_end < section_end:
            end = _find_preferred_break(text, start=start, target_end=target_end)
            if end <= start:
                end = target_end
        else:
            end = section_end

        trimmed_start, trimmed_end = _trim_span(text, start, end)
        if trimmed_end > trimmed_start:
            result.append((trimmed_start, trimmed_end))

        if end >= section_end:
            break

        next_start = max(section_start, end - overlap)
        next_start = _align_overlap_start(
            text,
            candidate=next_start,
            chunk_end=end,
            section_start=section_start,
            overlap=overlap,
        )
        next_start = _skip_whitespace_forward(text, next_start, section_end)

        # Hard progress invariant. This also preserves the legacy fixed-window
        # behavior for boundary-free text such as ``"A" * 600``.
        if next_start <= start:
            next_start = end
        start = next_start

    return result


def _find_preferred_break(text: str, *, start: int, target_end: int) -> int:
    window_length = target_end - start
    floor = start + max(1, int(window_length * 0.55))
    fragment = text[floor:target_end]

    for pattern in ("\n\n", "\n"):
        position = fragment.rfind(pattern)
        if position >= 0:
            return floor + position + len(pattern)

    sentence_end = None
    for match in _SENTENCE_END_RE.finditer(fragment):
        sentence_end = match.end()
    if sentence_end is not None:
        return floor + sentence_end

    for separator in ("。", "！", "？", "；", ";", "，", ",", " "):
        position = fragment.rfind(separator)
        if position >= 0:
            return floor + position + len(separator)

    return target_end


def _align_overlap_start(
    text: str,
    *,
    candidate: int,
    chunk_end: int,
    section_start: int,
    overlap: int,
) -> int:
    if overlap <= 0:
        return chunk_end

    candidate = max(section_start, candidate)
    if candidate >= chunk_end:
        return chunk_end

    max_shift = max(8, overlap // 3)
    search_end = min(chunk_end, candidate + max_shift)
    fragment = text[candidate:search_end]

    newline = fragment.find("\n")
    if newline >= 0 and candidate + newline + 1 < chunk_end:
        return candidate + newline + 1

    sentence = _SENTENCE_END_RE.search(fragment)
    if sentence is not None and candidate + sentence.end() < chunk_end:
        return candidate + sentence.end()

    space = fragment.find(" ")
    if space >= 0 and candidate + space + 1 < chunk_end:
        return candidate + space + 1

    return candidate


def _skip_whitespace_forward(text: str, start: int, end: int) -> int:
    while start < end and text[start].isspace():
        start += 1
    return start


def _trim_span(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _chunk_id(*, source: str, index: int, text: str) -> str:
    value = f"{source}:{index}:{text}"
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return f"chunk_{digest[:40]}"
