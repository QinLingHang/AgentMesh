from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from app.rag import (
    RetrievalHit,
    build_evidence_provenance,
)


# ============================================================
# Result Contract
# ============================================================


@dataclass(
    frozen=True,
    slots=True,
)
class GroundedAnswerGuardResult:
    """
    Deterministic validation result for the final answer.

    passed:
        True
            Original answer satisfies the active policy.

        False
            Original answer violated the policy and has been
            replaced by a deterministic safe fallback.

    action:
        allow
        safe_fallback
        not_applicable
    """

    answer: str
    passed: bool
    action: str
    violations: tuple[str, ...]


# ============================================================
# Internal Evidence Candidate
# ============================================================


@dataclass(
    frozen=True,
    slots=True,
)
class _EvidenceCandidate:
    hit: RetrievalHit
    overlap_count: int
    relative_score: float


# ============================================================
# Speculative Example Patterns
# ============================================================


_SPECULATIVE_PATTERNS: tuple[
    tuple[str, re.Pattern[str]],
    ...,
] = (
    (
        "e.g.",
        re.compile(
            r"\be\s*\.\s*g\s*\.?",
            flags=re.IGNORECASE,
        ),
    ),
    (
        "for example",
        re.compile(
            r"\bfor\s+example\b",
            flags=re.IGNORECASE,
        ),
    ),
    (
        "for instance",
        re.compile(
            r"\bfor\s+instance\b",
            flags=re.IGNORECASE,
        ),
    ),
    (
        "such as",
        re.compile(
            r"\bsuch\s+as\b",
            flags=re.IGNORECASE,
        ),
    ),
    (
        "possibly",
        re.compile(
            r"\bpossibly\b",
            flags=re.IGNORECASE,
        ),
    ),
)


# ============================================================
# Query Token Rules
# ============================================================


_STOPWORDS: set[str] = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "can",
    "do",
    "does",
    "explain",
    "for",
    "from",
    "how",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "please",
    "process",
    "the",
    "this",
    "to",
    "what",
    "with",
    "works",
}


# ============================================================
# Public Guard
# ============================================================


def guard_grounded_answer(
    *,
    task: str,
    answer: str,
    policy: str,
    retrieval_hits: Sequence[
        RetrievalHit
    ],
    max_evidence_items: int = 2,
    max_chars_per_item: int = 600,
) -> GroundedAnswerGuardResult:
    """
    Apply deterministic enforcement to the final answer.

    grounded_partial_only means:

        - partial evidence may be returned
        - unsupported speculative examples are forbidden
        - unsafe generated answers are discarded
        - fallback is built only from relevant retrieved
          evidence

    v2.0.4D adds:

        RetrievalHit selection
            +
        within-document relevant excerpt extraction

    This prevents irrelevant but technically true documents
    from polluting a safe fallback.
    """

    normalized_answer = (
        str(answer)
        .strip()
    )

    normalized_policy = (
        str(policy)
        .strip()
        .lower()
    )

    # --------------------------------------------------------
    # Policy not applicable
    # --------------------------------------------------------

    if (
        normalized_policy
        != "grounded_partial_only"
    ):
        return GroundedAnswerGuardResult(
            answer=normalized_answer,
            passed=True,
            action="not_applicable",
            violations=(),
        )

    # --------------------------------------------------------
    # Deterministic Validation
    # --------------------------------------------------------

    violations = (
        _find_speculative_violations(
            normalized_answer
        )
    )

    if not violations:
        return GroundedAnswerGuardResult(
            answer=normalized_answer,
            passed=True,
            action="allow",
            violations=(),
        )

    # --------------------------------------------------------
    # Deterministic Safe Fallback
    # --------------------------------------------------------

    safe_answer = (
        _build_safe_fallback(
            task=task,
            retrieval_hits=(
                retrieval_hits
            ),
            max_evidence_items=(
                max_evidence_items
            ),
            max_chars_per_item=(
                max_chars_per_item
            ),
        )
    )

    return GroundedAnswerGuardResult(
        answer=safe_answer,
        passed=False,
        action="safe_fallback",
        violations=tuple(
            violations
        ),
    )


# ============================================================
# Validation
# ============================================================


def _find_speculative_violations(
    answer: str,
) -> list[str]:

    violations: list[str] = []

    for (
        name,
        pattern,
    ) in _SPECULATIVE_PATTERNS:

        if pattern.search(
            answer
        ):
            violations.append(
                (
                    "unsupported_speculative_"
                    f"example:{name}"
                )
            )

    return violations


# ============================================================
# Safe Fallback
# ============================================================


def _build_safe_fallback(
    *,
    task: str,
    retrieval_hits: Sequence[
        RetrievalHit
    ],
    max_evidence_items: int,
    max_chars_per_item: int,
) -> str:

    effective_item_limit = max(
        1,
        int(
            max_evidence_items
        ),
    )

    effective_char_limit = max(
        100,
        int(
            max_chars_per_item
        ),
    )

    # ========================================================
    # Request-local Citation Identity
    #
    # IMPORTANT:
    #
    # Citation numbering must be based on the ORIGINAL
    # retrieval evidence order.
    #
    # Example:
    #
    #   [1] doc-A
    #   [2] doc-B
    #   [3] doc-C
    #
    # If Evidence Selection later removes doc-B, doc-C must
    # remain [3]. It must never be renumbered to [2].
    # ========================================================

    provenance = (
        build_evidence_provenance(
            retrieval_hits
        )
    )

    citation_labels: dict[
        str,
        str,
    ] = {
        item.document_id:
            item.citation_label

        for item
        in provenance
    }

    # ========================================================
    # Conservative Evidence Selection
    # ========================================================

    selected_hits = (
        _select_relevant_hits(
            task=task,
            retrieval_hits=(
                retrieval_hits
            ),
            max_items=(
                effective_item_limit
            ),
        )
    )

    if _contains_cjk(
        task
    ):
        return (
            _build_chinese_fallback(
                task=task,
                retrieval_hits=(
                    selected_hits
                ),
                citation_labels=(
                    citation_labels
                ),
                max_chars_per_item=(
                    effective_char_limit
                ),
            )
        )

    return (
        _build_english_fallback(
            task=task,
            retrieval_hits=(
                selected_hits
            ),
            citation_labels=(
                citation_labels
            ),
            max_chars_per_item=(
                effective_char_limit
            ),
        )
    )


# ============================================================
# Evidence Selection
# ============================================================


def _select_relevant_hits(
    *,
    task: str,
    retrieval_hits: Sequence[
        RetrievalHit
    ],
    max_items: int,
) -> list[RetrievalHit]:
    """
    Conservative deterministic evidence selection.

    Rules:

    1. Sort by retrieval score.
    2. The best hit is retained as the anchor evidence.
    3. Additional hits must satisfy BOTH:
       - sufficient lexical overlap with the task
       - score reasonably close to the top hit

    This intentionally prefers precision over recall because
    this function is used only for a safety fallback.
    """

    hits = list(
        retrieval_hits
    )

    if not hits:
        return []

    ordered_hits = sorted(
        hits,
        key=lambda item: (
            item.score
        ),
        reverse=True,
    )

    top_score = max(
        float(
            ordered_hits[
                0
            ]
            .score
        ),
        1e-9,
    )

    task_terms = (
        _extract_terms(
            task
        )
    )

    candidates: list[
        _EvidenceCandidate
    ] = []

    for hit in ordered_hits:

        document_text = (
            hit.document.text
            or ""
        )

        document_terms = (
            _extract_terms(
                document_text
            )
        )

        overlap_count = len(
            task_terms
            & document_terms
        )

        relative_score = (
            float(
                hit.score
            )
            / top_score
        )

        candidates.append(
            _EvidenceCandidate(
                hit=hit,
                overlap_count=(
                    overlap_count
                ),
                relative_score=(
                    relative_score
                ),
            )
        )

    selected: list[
        RetrievalHit
    ] = []

    # --------------------------------------------------------
    # Anchor evidence
    # --------------------------------------------------------

    top_candidate = (
        candidates[
            0
        ]
    )

    selected.append(
        top_candidate.hit
    )

    if (
        len(selected)
        >= max_items
    ):
        return selected

    # --------------------------------------------------------
    # Additional evidence
    #
    # Both relevance and retrieval confidence are required.
    # --------------------------------------------------------

    for candidate in (
        candidates[
            1:
        ]
    ):

        if (
            candidate.relative_score
            < 0.70
        ):
            continue

        if (
            candidate.overlap_count
            < 2
        ):
            continue

        selected.append(
            candidate.hit
        )

        if (
            len(selected)
            >= max_items
        ):
            break

    return selected


# ============================================================
# English Fallback
# ============================================================


def _build_english_fallback(
    *,
    task: str,
    retrieval_hits: Sequence[
        RetrievalHit
    ],
    citation_labels: dict[
        str,
        str,
    ],
    max_chars_per_item: int,
) -> str:

    sections: list[str] = []

    if retrieval_hits:

        sections.append(
            (
                "The current knowledge base provides "
                "only partial evidence for this request."
            )
        )

        evidence_lines: list[
            str
        ] = []

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

            citation_label = (
                citation_labels.get(
                    document_id
                )
            )

            # ------------------------------------------------
            # Fail closed.
            #
            # A selected evidence item without a valid
            # provenance identity must not be given an
            # invented citation number.
            # ------------------------------------------------

            if citation_label is None:
                continue

            source = (
                document.source
                or document.id
            )

            excerpt = (
                _extract_relevant_excerpt(
                    task=task,
                    text=(
                        document.text
                    ),
                    max_chars=(
                        max_chars_per_item
                    ),
                )
            )

            if not excerpt:
                continue

            evidence_lines.append(
                (
                    f"{citation_label} "
                    f"source={source}: "
                    f"{excerpt}"
                )
            )

        if evidence_lines:

            sections.append(
                (
                    "Supported evidence:\n"
                    + "\n".join(
                        evidence_lines
                    )
                )
            )

        sections.append(
            (
                "The available evidence is not "
                "sufficient to establish the remaining "
                "requested details. Those details cannot "
                "be determined from the current knowledge "
                "base."
            )
        )

    else:

        sections.append(
            (
                "The current knowledge base does not "
                "contain sufficient evidence to answer "
                "this request. The requested details "
                "cannot be determined from the current "
                "knowledge base."
            )
        )

    return "\n\n".join(
        sections
    )


# ============================================================
# Chinese Fallback
# ============================================================


def _build_chinese_fallback(
    *,
    task: str,
    retrieval_hits: Sequence[
        RetrievalHit
    ],
    citation_labels: dict[
        str,
        str,
    ],
    max_chars_per_item: int,
) -> str:

    sections: list[str] = []

    if retrieval_hits:

        sections.append(
            "当前知识库只能为该问题提供部分证据。"
        )

        evidence_lines: list[
            str
        ] = []

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

            citation_label = (
                citation_labels.get(
                    document_id
                )
            )

            if citation_label is None:
                continue

            source = (
                document.source
                or document.id
            )

            excerpt = (
                _extract_relevant_excerpt(
                    task=task,
                    text=(
                        document.text
                    ),
                    max_chars=(
                        max_chars_per_item
                    ),
                )
            )

            if not excerpt:
                continue

            evidence_lines.append(
                (
                    f"{citation_label} "
                    f"source={source}："
                    f"{excerpt}"
                )
            )

        if evidence_lines:

            sections.append(
                (
                    "当前证据明确支持的内容：\n"
                    + "\n".join(
                        evidence_lines
                    )
                )
            )

        sections.append(
            (
                "现有证据不足以确定问题中其余细节，"
                "因此这些内容无法根据当前知识库得出。"
            )
        )

    else:

        sections.append(
            (
                "当前知识库没有足够证据回答该问题，"
                "相关细节无法根据当前知识库确定。"
            )
        )

    return "\n\n".join(
        sections
    )


# ============================================================
# Relevant Excerpt Extraction
# ============================================================


def _extract_relevant_excerpt(
    *,
    task: str,
    text: str,
    max_chars: int,
) -> str:
    """
    Extract only the most task-relevant pieces of a document.

    The source text itself is never rewritten.

    Therefore the fallback remains extractive rather than
    generative.
    """

    value = (
        str(text)
        .strip()
    )

    if not value:
        return ""

    task_terms = (
        _extract_terms(
            task
        )
    )

    segments = (
        _split_evidence_segments(
            value
        )
    )

    if not segments:
        return (
            _truncate(
                value,
                max_chars,
            )
        )

    scored_segments: list[
        tuple[
            int,
            int,
            str,
        ]
    ] = []

    for index, segment in enumerate(
        segments
    ):

        segment_terms = (
            _extract_terms(
                segment
            )
        )

        overlap_count = len(
            task_terms
            & segment_terms
        )

        scored_segments.append(
            (
                overlap_count,
                index,
                segment,
            )
        )

    relevant_segments = [
        item

        for item
        in scored_segments

        if (
            item[
                0
            ]
            > 0
        )
    ]

    # If lexical extraction finds nothing, retain a short
    # extract from the selected top retrieval hit rather than
    # inventing content.
    if not relevant_segments:
        return (
            _truncate(
                value,
                max_chars,
            )
        )

    relevant_segments.sort(
        key=lambda item: (
            -item[
                0
            ],
            item[
                1
            ],
        )
    )

    chosen = (
        relevant_segments[
            :2
        ]
    )

    # Restore original document order.
    chosen.sort(
        key=lambda item: (
            item[
                1
            ]
        )
    )

    excerpt = " ".join(
        item[
            2
        ]

        for item
        in chosen
    )

    return (
        _truncate(
            excerpt,
            max_chars,
        )
    )


def _split_evidence_segments(
    text: str,
) -> list[str]:

    raw_parts = re.split(
        r"[\r\n]+|(?<=[。！？.!?；;])\s*",
        text,
    )

    return [
        part.strip()

        for part
        in raw_parts

        if part.strip()
    ]


# ============================================================
# Term Extraction
# ============================================================


def _extract_terms(
    text: str,
) -> set[str]:

    value = str(
        text
    )

    terms: set[str] = set()

    # --------------------------------------------------------
    # ASCII / technical terms
    #
    # Examples:
    # MCP
    # AgentMesh
    # Failure
    # Backoff
    # Runtime
    # --------------------------------------------------------

    ascii_terms = re.findall(
        r"[A-Za-z0-9][A-Za-z0-9_-]{1,}",
        value,
    )

    for raw_term in ascii_terms:

        term = (
            raw_term
            .strip()
            .lower()
        )

        if (
            len(term)
            < 2
        ):
            continue

        if (
            term
            in _STOPWORDS
        ):
            continue

        terms.add(
            term
        )

    # --------------------------------------------------------
    # CJK bigrams
    #
    # This allows pure Chinese questions to participate in
    # deterministic lexical relevance matching.
    # --------------------------------------------------------

    chinese_runs = re.findall(
        r"[\u4e00-\u9fff]+",
        value,
    )

    for run in chinese_runs:

        if (
            len(run)
            == 1
        ):
            terms.add(
                run
            )
            continue

        for index in range(
            len(run)
            - 1
        ):

            terms.add(
                run[
                    index:
                    index
                    + 2
                ]
            )

    return terms


# ============================================================
# Helpers
# ============================================================


def _contains_cjk(
    text: str,
) -> bool:

    return bool(
        re.search(
            r"[\u4e00-\u9fff]",
            text,
        )
    )


def _truncate(
    text: str,
    max_chars: int,
) -> str:

    value = " ".join(
        str(text)
        .strip()
        .split()
    )

    if (
        len(value)
        <= max_chars
    ):
        return value

    return (
        value[
            :max_chars
        ]
        + "..."
    )


__all__ = [
    "GroundedAnswerGuardResult",
    "guard_grounded_answer",
]