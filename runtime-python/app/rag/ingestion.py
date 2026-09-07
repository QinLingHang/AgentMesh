from __future__ import annotations

import hashlib
from typing import Any

from app.rag.runtime import (
    RetrievalDocument,
)


def chunk_text(
    *,
    text: str,
    source: str,
    metadata: (
        dict[str, Any]
        | None
    ) = None,
    chunk_size: int = 500,
    overlap: int = 100,
) -> list[
    RetrievalDocument
]:
    """
    Text → RetrievalDocument chunks.

    当前策略：

        chunk_size = 500 chars
        overlap = 100 chars

    后续可以替换：

        TokenSplitter
        MarkdownSplitter
        PDF-aware splitter
        Semantic chunker
    """

    text = (
        text.strip()
    )

    if not text:
        return []

    if chunk_size <= 0:
        raise ValueError(
            "chunk_size must be > 0"
        )

    if overlap < 0:
        raise ValueError(
            "overlap must be >= 0"
        )

    if overlap >= chunk_size:
        raise ValueError(
            (
                "overlap must be "
                "smaller than chunk_size"
            )
        )

    metadata = dict(
        metadata
        or {}
    )

    chunks: list[
        RetrievalDocument
    ] = []

    start = 0
    index = 0

    while (
        start
        < len(text)
    ):
        end = min(
            len(text),
            start + chunk_size,
        )

        chunk = (
            text[
                start:end
            ]
            .strip()
        )

        if chunk:
            chunk_id = (
                _chunk_id(
                    source=source,
                    index=index,
                    text=chunk,
                )
            )

            chunk_metadata = {
                **metadata,

                "chunkIndex":
                    index,

                "start":
                    start,

                "end":
                    end,
            }

            chunks.append(
                RetrievalDocument(
                    id=(
                        chunk_id
                    ),
                    text=(
                        chunk
                    ),
                    source=(
                        source
                    ),
                    metadata=(
                        chunk_metadata
                    ),
                )
            )

        if (
            end
            >= len(text)
        ):
            break

        start = (
            end - overlap
        )

        index += 1

    return chunks


def _chunk_id(
    *,
    source: str,
    index: int,
    text: str,
) -> str:

    value = (
        f"{source}:"
        f"{index}:"
        f"{text}"
    )

    digest = (
        hashlib.sha256(
            value.encode(
                "utf-8"
            )
        )
        .hexdigest()
    )

    return (
        f"chunk_{digest[:40]}"
    )