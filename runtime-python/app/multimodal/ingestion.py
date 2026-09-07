from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import Any

from app.multimodal.contracts import MultimodalIngestionStats, VisionAnalyzer
from app.rag.ingestion import chunk_text
from app.rag.runtime import RetrievalDocument


_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
_IMAGE_MEDIA_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
}

_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)(api[_-]?key|token|password|authorization|secret)(\s*[:=]\s*)([^\s,;]+)"
)
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+\-/]+=*")
_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.DOTALL,
)


def safe_knowledge_error(exc: Exception) -> str:
    """Keep operational context without persisting credentials from provider errors."""
    text = str(exc).replace("\r", " ").replace("\n", " ").strip()
    text = _PRIVATE_KEY_RE.sub("[redacted-private-key]", text)
    text = _BEARER_RE.sub("Bearer [redacted]", text)
    text = _SECRET_ASSIGNMENT_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}[redacted]", text)
    return f"{type(exc).__name__}: {text}"[:500]


# Backward-compatible private alias used by earlier targeted tests.
_safe_visual_error = safe_knowledge_error


@dataclass(slots=True)
class MultimodalIngestionResult:
    documents: list[RetrievalDocument]
    stats: MultimodalIngestionStats


def _page_texts(content: bytes) -> list[str]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("pypdf is required for PDF ingestion") from exc

    reader = PdfReader(io.BytesIO(content))
    return [(page.extract_text() or "").strip() for page in reader.pages]


def _render_pdf_pages(content: bytes, *, max_pages: int, dpi: int = 120) -> list[tuple[int, bytes]]:
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:  # pragma: no cover - graceful fallback caller handles
        raise RuntimeError("PyMuPDF is required for PDF visual ingestion") from exc

    result: list[tuple[int, bytes]] = []
    with fitz.open(stream=content, filetype="pdf") as document:
        for index in range(min(len(document), max_pages)):
            page = document[index]
            pix = page.get_pixmap(dpi=dpi, alpha=False)
            result.append((index + 1, pix.tobytes("png")))
    return result


def _base_metadata(base: dict[str, Any], *, modality: str, page_number: int | None = None) -> dict[str, Any]:
    metadata = {**base, "modality": modality, "evidenceKind": ("text" if modality == "text" else "visual")}
    if page_number is not None:
        metadata["pageNumber"] = page_number
    return metadata


async def ingest_multimodal_document(
    *,
    content: bytes,
    extension: str,
    source: str,
    base_metadata: dict[str, Any],
    vision_analyzer: VisionAnalyzer | None,
    chunk_size: int = 500,
    overlap: int = 100,
    max_visual_pages: int = 24,
) -> MultimodalIngestionResult:
    extension = extension.strip().lower().lstrip(".")
    documents: list[RetrievalDocument] = []
    text_chunks = 0
    visual_count = 0
    page_count = 0
    visual_status = "not_applicable"
    visual_error = ""

    if extension in _IMAGE_EXTENSIONS:
        page_count = 1
        if vision_analyzer is None:
            raise ValueError("image knowledge requires a configured vision analyzer")
        try:
            observation = await vision_analyzer.analyze_image(
                content=content,
                media_type=_IMAGE_MEDIA_TYPES[extension],
                source_name=source,
            )
        except Exception as exc:
            # Standalone-image failures used to bypass the PDF redaction path and
            # could project provider error text into the Go knowledge lifecycle.
            # Fail closed with a bounded, secret-redacted message instead.
            raise RuntimeError(safe_knowledge_error(exc)) from None
        visual_count = 1
        visual_status = "completed"
        documents.append(
            RetrievalDocument(
                id=f"{base_metadata['documentId']}_visual_1",
                text=observation.searchable_text(),
                source=source,
                metadata={
                    **_base_metadata(base_metadata, modality="image"),
                    "assetId": f"knowledge-file-{base_metadata['knowledgeFileId']}",
                    "visualType": observation.visual_type,
                    "visibleText": list(observation.visible_text),
                    "entities": list(observation.entities),
                    "relationships": list(observation.relationships),
                    "keyFacts": list(observation.key_facts),
                    "visionMetadata": observation.metadata,
                },
            )
        )
    elif extension == "pdf":
        pages = _page_texts(content)
        page_count = len(pages)
        global_chunk_index = 0
        for page_number, page_text in enumerate(pages, start=1):
            if not page_text:
                continue
            chunks = chunk_text(
                text=page_text,
                source=source,
                metadata=_base_metadata(base_metadata, modality="text", page_number=page_number),
                chunk_size=chunk_size,
                overlap=overlap,
            )
            for item in chunks:
                metadata = {
                    **dict(item.metadata),
                    "chunkIndex": global_chunk_index,
                    "pageChunkIndex": int(item.metadata.get("chunkIndex", 0)),
                }
                documents.append(
                    RetrievalDocument(
                        id=f"{base_metadata['documentId']}_p{page_number}_chunk{global_chunk_index}",
                        text=item.text,
                        source=source,
                        metadata=metadata,
                    )
                )
                global_chunk_index += 1
                text_chunks += 1

        if vision_analyzer is not None and page_count > 0:
            try:
                rendered = _render_pdf_pages(content, max_pages=max_visual_pages)
                for page_number, image_bytes in rendered:
                    observation = await vision_analyzer.analyze_image(
                        content=image_bytes,
                        media_type="image/png",
                        source_name=f"{source}#page-{page_number}",
                        page_number=page_number,
                    )
                    documents.append(
                        RetrievalDocument(
                            id=f"{base_metadata['documentId']}_page{page_number}_visual",
                            text=observation.searchable_text(),
                            source=source,
                            metadata={
                                **_base_metadata(base_metadata, modality="page", page_number=page_number),
                                "assetId": f"knowledge-file-{base_metadata['knowledgeFileId']}-page-{page_number}",
                                "visualType": observation.visual_type,
                                "visibleText": list(observation.visible_text),
                                "entities": list(observation.entities),
                                "relationships": list(observation.relationships),
                                "keyFacts": list(observation.key_facts),
                                "visionMetadata": observation.metadata,
                            },
                        )
                    )
                    visual_count += 1
                if visual_count:
                    visual_status = "partial" if page_count > max_visual_pages else "completed"
                else:
                    visual_status = "empty"
            except Exception as exc:
                visual_status = "failed"
                visual_error = safe_knowledge_error(exc)
        else:
            visual_status = "disabled" if page_count else "not_applicable"
    else:
        # Text-first formats retain the P1 ingestion behavior while receiving
        # explicit modality metadata for V2 retrieval.
        from app.knowledge.parser import parse_document_bytes

        text = parse_document_bytes(extension=extension, content=content)
        chunks = chunk_text(
            text=text,
            source=source,
            metadata=_base_metadata(base_metadata, modality="text"),
            chunk_size=chunk_size,
            overlap=overlap,
        )
        for index, item in enumerate(chunks):
            metadata = {**dict(item.metadata), "chunkIndex": index}
            documents.append(
                RetrievalDocument(
                    id=f"{base_metadata['documentId']}_chunk{index}",
                    text=item.text,
                    source=source,
                    metadata=metadata,
                )
            )
        text_chunks = len(chunks)

    if not documents:
        raise ValueError("knowledge document produced zero evidence")

    return MultimodalIngestionResult(
        documents=documents,
        stats=MultimodalIngestionStats(
            total_documents=len(documents),
            text_chunks=text_chunks,
            visual_evidence=visual_count,
            page_count=page_count,
            visual_status=visual_status,
            visual_error=visual_error,
        ),
    )
