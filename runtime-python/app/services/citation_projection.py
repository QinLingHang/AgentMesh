from __future__ import annotations

from typing import (
    Sequence,
)

from app.rag import (
    EvidenceProvenance,
)

from app.schemas import (
    RuntimeCitation,
)


# ============================================================
# Runtime Citation Projection
# ============================================================


def project_used_citations(
    *,
    provenance: Sequence[
        EvidenceProvenance
    ],
    used_citation_ids: Sequence[
        int
    ],
) -> list[
    RuntimeCitation
]:
    """
    Project internal EvidenceProvenance into the public
    RuntimeCitation API model.

    IMPORTANT:

    available evidence
        !=
    used evidence

    Example:

        available:
            [1] RAG document
            [2] MCP document
            [3] Deployment document
            [4] Architecture document

        final answer:
            "... Milvus ... [1]"

        response citations:
            [1]

    NOT:
            [1] [2] [3] [4]

    Rules:

    1. Only citations actually referenced by the final
       validated answer are returned.

    2. Preserve first-use order.

       Example:

           answer citations:
               [3] [1] [3]

           response:
               [3], [1]

    3. Repeated citations are deduplicated.

    4. Unknown citation IDs fail closed.

       This function runs after Citation Guard, so an unknown
       ID indicates an internal contract violation and must
       not be silently ignored.

    5. Runtime diagnostics are not projected.
    """

    if not used_citation_ids:
        return []

    provenance_by_id: dict[
        int,
        EvidenceProvenance,
    ] = {
        int(
            item.citation_id
        ):
            item

        for item
        in provenance
    }

    result: list[
        RuntimeCitation
    ] = []

    seen: set[
        int
    ] = set()

    for raw_citation_id in (
        used_citation_ids
    ):

        citation_id = int(
            raw_citation_id
        )

        if citation_id in seen:
            continue

        evidence = (
            provenance_by_id.get(
                citation_id
            )
        )

        if evidence is None:
            raise ValueError(
                (
                    "cannot project unknown "
                    "citation id: "
                    f"[{citation_id}]"
                )
            )

        seen.add(
            citation_id
        )

        result.append(
            RuntimeCitation(
                citation_id=(
                    evidence
                    .citation_id
                ),

                label=(
                    evidence
                    .citation_label
                ),

                document_id=(
                    evidence
                    .document_id
                ),

                source=(
                    evidence
                    .source
                ),

                score=round(
                    float(
                        evidence
                        .score
                    ),
                    6,
                ),

                document_type=(
                    evidence
                    .document_type
                ),

                chunk_index=(
                    evidence
                    .chunk_index
                ),

                start=(
                    evidence
                    .start
                ),

                end=(
                    evidence
                    .end
                ),
            )
        )

    return result


__all__ = [
    "project_used_citations",
]