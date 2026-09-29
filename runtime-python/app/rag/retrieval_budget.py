from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class RetrievalBudget:
    """Resolved retrieval budget for one Agentic RAG round.

    final_top_k is the number of hits exposed to evidence grading and callers.
    retrieval_top_k is the number requested from each retrieval query.
    candidate_pool_k is the bounded cross-query/cross-round pool retained before
    the final narrow selection.
    """

    final_top_k: int
    retrieval_top_k: int
    candidate_pool_k: int
    expanded: bool
    reason: str


class CandidateBudgetPolicy(Protocol):
    def resolve(
        self,
        *,
        final_top_k: int,
        round_index: int,
        enable_multi_query: bool,
        enable_decomposition: bool,
    ) -> RetrievalBudget:
        ...


class AdaptiveCandidateBudgetPolicy:
    """Bounded retrieve-wide / rerank-narrow candidate budgeting.

    The policy intentionally keeps simple first-round retrieval unchanged.
    Expansion is reserved for retrieval strategies that need broader coverage:

    * multi-query:      1.5x final top-k
    * decomposition:    2.0x final top-k
    * round 2+:         2.0x final top-k because prior evidence was insufficient

    A hard cap bounds provider cost and latency.  The cap never reduces a
    caller-requested final top-k; if final_top_k is already above the configured
    cap, final_top_k becomes the effective minimum cap.
    """

    def __init__(
        self,
        *,
        hard_cap: int = 20,
        multi_query_multiplier: float = 1.5,
        decomposition_multiplier: float = 2.0,
        retry_multiplier: float = 2.0,
    ) -> None:
        self.hard_cap = max(1, int(hard_cap))
        self.multi_query_multiplier = max(
            1.0,
            float(multi_query_multiplier),
        )
        self.decomposition_multiplier = max(
            1.0,
            float(decomposition_multiplier),
        )
        self.retry_multiplier = max(
            1.0,
            float(retry_multiplier),
        )

    @staticmethod
    def _scaled(
        value: int,
        multiplier: float,
    ) -> int:
        return max(
            value,
            int(math.ceil(value * multiplier)),
        )

    def resolve(
        self,
        *,
        final_top_k: int,
        round_index: int,
        enable_multi_query: bool,
        enable_decomposition: bool,
    ) -> RetrievalBudget:
        final_k = max(1, int(final_top_k))
        effective_cap = max(final_k, self.hard_cap)

        retrieval_k = final_k
        reasons: list[str] = []

        if enable_multi_query:
            retrieval_k = max(
                retrieval_k,
                self._scaled(
                    final_k,
                    self.multi_query_multiplier,
                ),
            )
            reasons.append("multi_query")

        if enable_decomposition:
            retrieval_k = max(
                retrieval_k,
                self._scaled(
                    final_k,
                    self.decomposition_multiplier,
                ),
            )
            reasons.append("decomposition")

        # Reaching a later round means the previous evidence grade was
        # insufficient; expand the search window without adding another model
        # decision or widening the final context returned to the caller.
        if int(round_index) > 0:
            retrieval_k = max(
                retrieval_k,
                self._scaled(
                    final_k,
                    self.retry_multiplier,
                ),
            )
            reasons.append("evidence_retry")

        retrieval_k = min(
            retrieval_k,
            effective_cap,
        )

        expanded = retrieval_k > final_k

        # Only expanded paths retain a wider union.  Simple first-round
        # retrieval therefore preserves the previous memory/latency behavior.
        candidate_pool_k = (
            effective_cap
            if expanded
            else final_k
        )

        return RetrievalBudget(
            final_top_k=final_k,
            retrieval_top_k=retrieval_k,
            candidate_pool_k=candidate_pool_k,
            expanded=expanded,
            reason=(
                "+".join(reasons)
                if reasons
                else "base"
            ),
        )


__all__ = [
    "RetrievalBudget",
    "CandidateBudgetPolicy",
    "AdaptiveCandidateBudgetPolicy",
]
