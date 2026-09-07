from __future__ import annotations

import re

from dataclasses import (
    dataclass,
)

from typing import (
    Sequence,
)

from app.rag import (
    EvidenceProvenance,
)


# ============================================================
# Result Contract
# ============================================================


@dataclass(
    frozen=True,
    slots=True,
)
class CitationGuardResult:
    """
    Deterministic citation validation result.

    action:

        allow
            Citation structure is valid.

        safe_rejection
            Citation contract was violated and the original
            answer must not be returned.

        not_applicable
            No evidence provenance exists and the answer does
            not contain citation markers.
    """

    answer: str

    passed: bool

    action: str

    citations: tuple[
        int,
        ...
    ]

    invalid_citations: tuple[
        int,
        ...
    ]

    violations: tuple[
        str,
        ...
    ]


# ============================================================
# Citation Pattern
# ============================================================


_CITATION_PATTERN = re.compile(
    r"\[(\d+)\]"
)


# ============================================================
# Public Guard
# ============================================================


def guard_answer_citations(
    *,
    task: str,
    answer: str,
    provenance: Sequence[
        EvidenceProvenance
    ],
    require_citation: bool,
) -> CitationGuardResult:
    """
    Deterministically validate citation references.

    v2.0.5C scope:

    1. Citation IDs must exist in EvidenceProvenance.

    2. If citation is required and evidence exists,
       at least one valid citation must appear.

    3. If no evidence exists, the answer must not invent
       citation IDs.

    4. Validation failure is fail-closed:
       the original answer is replaced with a safe message.

    IMPORTANT:

    This version validates citation structure and existence.

    It does NOT yet prove semantic entailment between an
    individual claim and the cited evidence.
    """

    normalized_answer = (
        str(answer)
        .strip()
    )

    citations = (
        _extract_citations(
            normalized_answer
        )
    )

    valid_citation_ids = {
        int(
            item.citation_id
        )

        for item
        in provenance
    }

    invalid_citations = tuple(
        sorted(
            {
                citation_id

                for citation_id
                in citations

                if (
                    citation_id
                    not in valid_citation_ids
                )
            }
        )
    )

    violations: list[str] = []

    # --------------------------------------------------------
    # Invalid / hallucinated citation IDs
    # --------------------------------------------------------

    for citation_id in invalid_citations:
        violations.append(
            (
                "unknown_citation:"
                f"[{citation_id}]"
            )
        )

    # --------------------------------------------------------
    # Citation required but missing
    # --------------------------------------------------------

    if (
        provenance
        and require_citation
        and not citations
    ):
        violations.append(
            "missing_required_citation"
        )

    # --------------------------------------------------------
    # Fail closed
    # --------------------------------------------------------

    if violations:
        return CitationGuardResult(
            answer=(
                _build_safe_rejection(
                    task=task,
                    answer=(
                        normalized_answer
                    ),
                )
            ),

            passed=False,

            action=(
                "safe_rejection"
            ),

            citations=(
                citations
            ),

            invalid_citations=(
                invalid_citations
            ),

            violations=tuple(
                violations
            ),
        )

    # --------------------------------------------------------
    # No evidence and no citation markers
    # --------------------------------------------------------

    if not provenance:
        return CitationGuardResult(
            answer=normalized_answer,

            passed=True,

            action=(
                "not_applicable"
            ),

            citations=(),

            invalid_citations=(),

            violations=(),
        )

    # --------------------------------------------------------
    # Valid citation structure
    # --------------------------------------------------------

    return CitationGuardResult(
        answer=normalized_answer,

        passed=True,

        action="allow",

        citations=citations,

        invalid_citations=(),

        violations=(),
    )


# ============================================================
# Extraction
# ============================================================


def _extract_citations(
    answer: str,
) -> tuple[
    int,
    ...
]:
    """
    Preserve citation occurrence order.

    Example:

        A [1]. B [1]. C [3].

    becomes:

        (1, 1, 3)

    Duplicate citations are valid because multiple claims may
    legitimately reference the same evidence.
    """

    return tuple(
        int(
            value
        )

        for value
        in _CITATION_PATTERN.findall(
            answer
        )
    )


# ============================================================
# Safe Failure Response
# ============================================================


def _build_safe_rejection(
    *,
    task: str,
    answer: str,
) -> str:

    if (
        _contains_cjk(task)
        or _contains_cjk(answer)
    ):
        return (
            "当前回答的证据引用未能通过校验，"
            "因此为避免返回无法验证的引用内容，"
            "本次回答已被安全拦截。"
        )

    return (
        "The answer could not be returned because its "
        "evidence citations could not be validated against "
        "the retrieved knowledge."
    )


# ============================================================
# Helpers
# ============================================================


def _contains_cjk(
    text: str,
) -> bool:

    return bool(
        re.search(
            r"[\u4e00-\u9fff]",
            str(text),
        )
    )


__all__ = [
    "CitationGuardResult",
    "guard_answer_citations",
]