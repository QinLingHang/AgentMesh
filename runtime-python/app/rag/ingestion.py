from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from app.document_text_normalization import normalize_document_text
from app.rag.chunking import (
    ChunkSpan,
    ChunkingPolicy,
    StructuralBlock,
    extract_structural_blocks,
    legacy_fixed_window_spans,
    pack_blocks,
)
from app.rag.runtime import RetrievalDocument


_CONTEXT_PRESERVING_STRATEGY = "context_preserving_structure_v2"
_FIXED_FALLBACK_STRATEGY = "fixed_window_fallback_v1"


def chunk_text(
    *,
    text: str,
    source: str,
    metadata: dict[str, Any] | None = None,
    chunk_size: int = 500,
    overlap: int = 100,
) -> list[RetrievalDocument]:
    """Split normalized text into source-aligned retrieval chunks.

    V2 treats document structure as a *preferred* boundary rather than a hard
    instruction to emit a chunk. Adjacent small blocks are packed together,
    oversized regions alone are recursively split, and overlap is introduced
    only by those forced oversized splits. Truly unstructured text keeps the
    legacy fixed-window behavior for deterministic fallback compatibility.

    ``start`` and ``end`` offsets always refer to the normalized text consumed
    here, and every returned ``chunk.text`` is exactly ``normalized[start:end]``.
    No synthetic heading prefix or rewritten context is inserted.
    """
    policy = ChunkingPolicy.from_legacy(chunk_size=chunk_size, overlap=overlap)

    normalized = normalize_document_text(text)
    if not normalized:
        return []

    base_metadata = dict(metadata or {})
    document_type = _document_type(source=source, metadata=base_metadata)
    analysis = extract_structural_blocks(normalized, document_type=document_type)

    if analysis.has_structure:
        spans = pack_blocks(
            normalized,
            blocks=analysis.blocks,
            policy=policy,
        )
        strategy = _CONTEXT_PRESERVING_STRATEGY
    else:
        spans = legacy_fixed_window_spans(normalized, policy=policy)
        strategy = _FIXED_FALLBACK_STRATEGY

    return _project_documents(
        normalized,
        source=source,
        base_metadata=base_metadata,
        blocks=analysis.blocks,
        spans=spans,
        strategy=strategy,
        policy=policy,
        document_type=document_type,
    )


def _project_documents(
    text: str,
    *,
    source: str,
    base_metadata: dict[str, Any],
    blocks: tuple[StructuralBlock, ...],
    spans: list[ChunkSpan],
    strategy: str,
    policy: ChunkingPolicy,
    document_type: str,
) -> list[RetrievalDocument]:
    chunks: list[RetrievalDocument] = []
    previous_end: int | None = None

    for span in spans:
        start, end = _trim_span(text, span.start, span.end)
        if end <= start:
            continue
        if end - start > policy.max_chars:
            raise RuntimeError("chunking invariant violated: chunk exceeds hard max")

        chunk = text[start:end]
        # Citation/source-offset invariant. Keep it explicit because changing the
        # chunker must never silently create synthetic retrieval text.
        if chunk != text[start:end]:  # pragma: no cover - defensive identity guard
            raise RuntimeError("chunking invariant violated: source span mismatch")

        intersecting = _intersecting_blocks(blocks, start=start, end=end)
        metadata = _chunk_metadata(
            base_metadata=base_metadata,
            index=len(chunks),
            start=start,
            end=end,
            chunk=chunk,
            strategy=strategy,
            split_reason=span.split_reason,
            previous_end=previous_end,
            blocks=intersecting,
            document_type=document_type,
            policy=policy,
        )

        chunks.append(
            RetrievalDocument(
                id=_chunk_id(source=source, index=len(chunks), text=chunk),
                text=chunk,
                source=source,
                metadata=metadata,
            )
        )
        previous_end = end

    return chunks


def _chunk_metadata(
    *,
    base_metadata: dict[str, Any],
    index: int,
    start: int,
    end: int,
    chunk: str,
    strategy: str,
    split_reason: str,
    previous_end: int | None,
    blocks: tuple[StructuralBlock, ...],
    document_type: str,
    policy: ChunkingPolicy,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        **base_metadata,
        "chunkIndex": index,
        "start": start,
        "end": end,
        "chunkLength": len(chunk),
        "chunkStrategy": strategy,
        "splitReason": split_reason,
        "overlapChars": (
            max(0, previous_end - start) if previous_end is not None else 0
        ),
        "sourceDocumentType": document_type,
        "chunkPolicy": {
            "minChars": policy.min_chars,
            "targetChars": policy.target_chars,
            "maxChars": policy.max_chars,
            "overlapChars": policy.overlap_chars,
        },
    }

    block_types = _unique(block.block_type for block in blocks)
    section_ids = _unique(block.section_id for block in blocks)
    heading_paths = _unique_tuple(block.heading_path for block in blocks if block.heading_path)

    if block_types:
        metadata["blockTypes"] = block_types
    if section_ids:
        metadata["sectionIds"] = section_ids
        metadata["containsMultipleSections"] = len(section_ids) > 1
    if heading_paths:
        metadata["headingPaths"] = [list(path) for path in heading_paths]
        # Preserve the legacy convenience keys for consumers that expect one
        # primary heading while exposing all crossed sections separately.
        metadata["headingPath"] = list(heading_paths[0])
        metadata["heading"] = heading_paths[0][-1]

    return metadata


def _intersecting_blocks(
    blocks: tuple[StructuralBlock, ...],
    *,
    start: int,
    end: int,
) -> tuple[StructuralBlock, ...]:
    return tuple(block for block in blocks if block.end > start and block.start < end)


def _document_type(*, source: str, metadata: dict[str, Any]) -> str:
    value = str(metadata.get("documentType", "") or "").strip().lower().lstrip(".")
    if value:
        return value
    suffix = Path(source).suffix.strip().lower().lstrip(".")
    return suffix or "text"


def _unique(values) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _unique_tuple(values) -> list[tuple[str, ...]]:
    result: list[tuple[str, ...]] = []
    seen: set[tuple[str, ...]] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


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
