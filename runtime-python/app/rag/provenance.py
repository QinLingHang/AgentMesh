from __future__ import annotations

from dataclasses import (
    dataclass,
    field,
)

from typing import (
    Any,
    Sequence,
)

from app.rag.runtime import (
    RetrievalHit,
)


# ============================================================
# Metadata Policy
# ============================================================


_TRANSIENT_METADATA_KEYS: set[str] = {
    # User / tenant routing metadata.
    # Citation provenance must not expose it.
    "userId",

    # Retrieval execution metadata.
    "retrievalMode",
    "rrfScore",
    "reranker",
    "preRerankScore",
    "modelRerankScore",
    "ragDiagnostics",
}


# ============================================================
# Evidence Provenance Contract
# ============================================================


@dataclass(
    frozen=True,
    slots=True,
)
class EvidenceProvenance:
    """
    Request-local evidence identity.

    IMPORTANT:

    citation_id
        Local citation number inside ONE answer.

        Example:
            1
            2
            3

    citation_label
        Human-readable citation marker.

        Example:
            [1]
            [2]
            [3]

    document_id
        Stable knowledge-document / chunk identity.

        Example:
            chunk_de4e40...

    These concepts must NOT be mixed.

    The same document may be:

        [1] in request A

    and:

        [3] in request B

    while its document_id remains unchanged.
    """

    citation_id: int

    document_id: str

    source: str

    score: float

    document_type: (
        str
        | None
    ) = None

    chunk_index: (
        int
        | None
    ) = None

    start: (
        int
        | None
    ) = None

    end: (
        int
        | None
    ) = None

    metadata: dict[
        str,
        Any,
    ] = field(
        default_factory=dict
    )

    @property
    def citation_label(
        self,
    ) -> str:
        return (
            f"[{self.citation_id}]"
        )


# ============================================================
# Builder
# ============================================================


def build_evidence_provenance(
    retrieval_hits: Sequence[
        RetrievalHit
    ],
) -> list[
    EvidenceProvenance
]:
    """
    Build stable request-local evidence provenance.

    Rules:

    1. Preserve the final RetrievalHit order.

       Citation numbering therefore follows the exact
       evidence order visible to the downstream Agent.

    2. Deduplicate by document.id.

       The first ranked occurrence wins.

       Upstream Agentic Retrieval already performs
       document-level deduplication, but this builder
       keeps the contract defensive.

    3. Do not mutate RetrievalHit / RetrievalDocument.

    4. Do not expose user routing data or retrieval
       diagnostics as citation metadata.

    5. document.id is required.

       Provenance without a stable document identity
       would make citation validation unreliable.
    """

    result: list[
        EvidenceProvenance
    ] = []

    seen_document_ids: set[
        str
    ] = set()

    for hit in retrieval_hits:

        document = (
            hit.document
        )

        document_id = (
            str(
                document.id
            )
            .strip()
        )

        if not document_id:
            raise ValueError(
                (
                    "evidence provenance "
                    "requires non-empty "
                    "document id"
                )
            )

        if (
            document_id
            in seen_document_ids
        ):
            continue

        seen_document_ids.add(
            document_id
        )

        raw_metadata = dict(
            document.metadata
            or {}
        )

        safe_metadata = (
            _sanitize_metadata(
                raw_metadata
            )
        )

        source = (
            str(
                document.source
                or document_id
            )
            .strip()
        )

        result.append(
            EvidenceProvenance(
                citation_id=(
                    len(result)
                    + 1
                ),

                document_id=(
                    document_id
                ),

                source=(
                    source
                ),

                score=float(
                    hit.score
                ),

                document_type=(
                    _as_optional_str(
                        raw_metadata.get(
                            "documentType"
                        )
                    )
                ),

                chunk_index=(
                    _as_optional_int(
                        raw_metadata.get(
                            "chunkIndex"
                        )
                    )
                ),

                start=(
                    _as_optional_int(
                        raw_metadata.get(
                            "start"
                        )
                    )
                ),

                end=(
                    _as_optional_int(
                        raw_metadata.get(
                            "end"
                        )
                    )
                ),

                metadata=(
                    safe_metadata
                ),
            )
        )

    return result


# ============================================================
# Metadata Helpers
# ============================================================


def _sanitize_metadata(
    metadata: dict[
        str,
        Any,
    ],
) -> dict[
    str,
    Any,
]:
    """
    Preserve source/document metadata while removing:

    - user routing information
    - retrieval diagnostics
    - reranker internals

    Future metadata such as:

        title
        fileName
        page
        url
        knowledgeBaseId
        section

    can pass through automatically.
    """

    return {
        key: value

        for (
            key,
            value,
        ) in metadata.items()

        if (
            key
            not in _TRANSIENT_METADATA_KEYS
        )
    }


def _as_optional_str(
    value: Any,
) -> str | None:

    if value is None:
        return None

    normalized = (
        str(value)
        .strip()
    )

    if not normalized:
        return None

    return normalized


def _as_optional_int(
    value: Any,
) -> int | None:

    if value is None:
        return None

    try:
        return int(
            value
        )

    except (
        TypeError,
        ValueError,
    ):
        return None


__all__ = [
    "EvidenceProvenance",
    "build_evidence_provenance",
]