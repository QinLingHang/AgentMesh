from __future__ import annotations

import io
import json
import re
from typing import Iterable

from app.document_text_normalization import (
    normalize_document_text,
    normalize_pdf_pages,
)


_HEADING_STYLE_RE = re.compile(r"^Heading\s+(\d+)$", re.IGNORECASE)


def _decode_text(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def _parse_pdf(content: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - deployment guard
        raise RuntimeError("pypdf is required for PDF ingestion") from exc

    reader = PdfReader(io.BytesIO(content))
    pages = normalize_pdf_pages([(page.extract_text() or "") for page in reader.pages])
    return "\n\n".join(page for page in pages if page)


def _table_rows(table) -> Iterable[str]:
    for row in table.rows:
        values = [normalize_document_text(cell.text) for cell in row.cells]
        if any(values):
            yield " | ".join(values)


def _parse_docx(content: bytes) -> str:
    try:
        from docx import Document
    except ImportError as exc:  # pragma: no cover - deployment guard
        raise RuntimeError("python-docx is required for DOCX ingestion") from exc

    document = Document(io.BytesIO(content))
    blocks: list[str] = []

    for paragraph in document.paragraphs:
        value = normalize_document_text(paragraph.text)
        if not value:
            continue

        style_name = ""
        if paragraph.style is not None:
            style_name = str(getattr(paragraph.style, "name", "") or "")
        heading_match = _HEADING_STYLE_RE.match(style_name)
        if heading_match:
            level = min(6, max(1, int(heading_match.group(1))))
            blocks.append(f"{'#' * level} {value}")
        else:
            blocks.append(value)

    for table in document.tables:
        rows = list(_table_rows(table))
        if rows:
            blocks.append("\n".join(rows))

    return "\n\n".join(blocks)


def parse_document_bytes(
    *,
    extension: str,
    content: bytes,
) -> str:
    extension = extension.strip().lower().lstrip(".")

    if not content:
        raise ValueError("knowledge file is empty")

    if extension in {"txt", "md", "markdown", "csv"}:
        text = _decode_text(content)
    elif extension == "json":
        decoded = _decode_text(content)
        try:
            text = json.dumps(json.loads(decoded), ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            text = decoded
    elif extension == "pdf":
        text = _parse_pdf(content)
    elif extension == "docx":
        text = _parse_docx(content)
    else:
        raise ValueError(f"unsupported knowledge extension: {extension}")

    text = normalize_document_text(text)
    if not text:
        raise ValueError(
            "no extractable text found; scanned PDF OCR is not enabled in knowledge"
        )
    return text
