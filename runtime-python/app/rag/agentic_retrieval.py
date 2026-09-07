from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Protocol, Sequence

from app.rag.runtime import RetrievalHit, Retriever


# ============================================================
# Query Transformer Contract
# ============================================================


class QueryTransformer(Protocol):
    async def rewrite(
        self,
        query: str,
        *,
        round_index: int,
        previous_query: str | None = None,
        feedback: str | None = None,
    ) -> str:
        ...

    async def multi_query(
        self,
        query: str,
    ) -> list[str]:
        ...

    async def decompose(
        self,
        query: str,
    ) -> list[str]:
        ...


def _normalize_text(value: str) -> str:
    return " ".join(str(value).strip().split())


def _deduplicate_texts(
    values: Sequence[str],
) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    for value in values:
        normalized = _normalize_text(value)
        if not normalized:
            continue

        key = normalized.lower()
        if key in seen:
            continue

        seen.add(key)
        result.append(normalized)

    return result


class HeuristicQueryTransformer:
    """
    Deterministic Query Intelligence baseline.

    用途：
    1. 单元测试稳定；
    2. 本地开发不依赖模型；
    3. ModelBackedQueryTransformer 失败时作为 fallback。
    """

    async def rewrite(
        self,
        query: str,
        *,
        round_index: int,
        previous_query: str | None = None,
        feedback: str | None = None,
    ) -> str:
        normalized = _normalize_text(query)

        if not normalized:
            return ""

        # 第一轮没有历史反馈，保持 deterministic baseline。
        if round_index <= 0:
            return normalized

        previous = _normalize_text(
            previous_query or ""
        )

        gap = _normalize_text(
            feedback or ""
        )

        # Round 2+：把上一轮证据缺口带入下一轮检索。
        if gap:
            gap = gap[:300]

            return _normalize_text(
                (
                    f"{normalized} "
                    f"evidence gap: {gap} "
                    f"round {round_index + 1}"
                )
            )

        # 没有 feedback 时保持原有 round 语义。
        if previous:
            return _normalize_text(
                (
                    f"{normalized} "
                    f"previous query: {previous} "
                    f"round {round_index + 1}"
                )
            )

        return (
            f"{normalized} "
            f"round {round_index + 1}"
        )

    async def multi_query(
        self,
        query: str,
    ) -> list[str]:
        normalized = _normalize_text(query)

        if not normalized:
            return []

        return _deduplicate_texts(
            [
                normalized,
                f"{normalized} architecture",
                f"{normalized} implementation",
            ]
        )

    async def decompose(
        self,
        query: str,
    ) -> list[str]:
        normalized = _normalize_text(query)

        if not normalized:
            return []

        parts = re.split(
            (
                r"[，,。.!！？?；;：:]+"
                r"|(?:\s+(?:and|or)\s+)"
                r"|(?:以及|并且|同时)"
            ),
            normalized,
            flags=re.IGNORECASE,
        )

        result = _deduplicate_texts(
            [part for part in parts if part]
        )

        if len(result) <= 1:
            return [normalized]

        return result


# ============================================================
# Evidence Grading Contract
# ============================================================


@dataclass(frozen=True, slots=True)
class EvidenceGrade:
    relevance: float
    coverage: float
    confidence: float
    sufficient: bool
    reason: str


class EvidenceGrader(Protocol):
    async def grade(
        self,
        query: str,
        hits: Sequence[RetrievalHit],
    ) -> EvidenceGrade:
        ...


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _safe_hit_score(hit: RetrievalHit) -> float:
    try:
        return _clamp01(float(hit.score))
    except (TypeError, ValueError):
        return 0.0


class HeuristicEvidenceGrader:
    """
    Deterministic Evidence Grader baseline.

    Model-backed Evidence Grader 位于 model_intelligence.py。
    这里仅负责稳定 baseline / fallback。
    """

    def __init__(
        self,
        *,
        min_hits: int = 1,
        min_relevance: float = 0.50,
    ) -> None:
        self.min_hits = max(1, int(min_hits))
        self.min_relevance = _clamp01(min_relevance)

    async def grade(
        self,
        query: str,
        hits: Sequence[RetrievalHit],
    ) -> EvidenceGrade:
        if not hits:
            return EvidenceGrade(
                relevance=0.0,
                coverage=0.0,
                confidence=0.95,
                sufficient=False,
                reason="no retrieval evidence",
            )

        scores = [
            _safe_hit_score(hit)
            for hit in hits
        ]

        relevance = max(
            scores,
            default=0.0,
        )

        coverage = _clamp01(
            len(hits) / float(self.min_hits)
        )

        sufficient = (
            len(hits) >= self.min_hits
            and relevance >= self.min_relevance
        )

        return EvidenceGrade(
            relevance=relevance,
            coverage=coverage,
            confidence=0.95,
            sufficient=sufficient,
            reason=(
                "heuristic evidence is sufficient"
                if sufficient
                else "heuristic evidence is insufficient"
            ),
        )


# ============================================================
# Agentic Retrieval Result Models
# ============================================================


@dataclass(slots=True)
class AgenticRetrievalRound:
    """One Agentic Retrieval round snapshot."""

    round_index: int
    query: str
    queries: list[str]
    hits: list[RetrievalHit]
    grade: EvidenceGrade

    @property
    def round_number(self) -> int:
        return self.round_index + 1

    @property
    def sufficient(self) -> bool:
        return self.grade.sufficient

    @property
    def hit_count(self) -> int:
        """
        RuntimeEngine trace contract.

        engine.py reads item.hit_count when building roundDetails.
        """
        return len(self.hits)


@dataclass(slots=True)
class AgenticRetrievalResult:
    """Final Agentic Retrieval result."""

    query: str
    hits: list[RetrievalHit]
    rounds: list[AgenticRetrievalRound]
    grade: EvidenceGrade
    sufficient: bool
    stopped_reason: str

    @property
    def final_grade(self) -> EvidenceGrade:
        return self.grade


# ============================================================
# Agentic Retrieval Executor
# ============================================================


class AgenticRetrievalExecutor:
    """
    Deterministic Agentic Retrieval controller.

    Loop:

        Query
          ↓
        Query Intelligence
          ↓
        Retrieve
          ↓
        Deduplicate / Merge
          ↓
        Evidence Grade
          ↓
        sufficient?
          ├─ True  → stop
          └─ False → next round with previous evidence feedback

    QueryTransformer / EvidenceGrader are injected through contracts.
    """

    def __init__(
        self,
        *,
        retriever: Retriever,
        transformer: QueryTransformer | None = None,
        query_transformer: QueryTransformer | None = None,
        grader: EvidenceGrader | None = None,
    ) -> None:
        if (
            transformer is not None
            and query_transformer is not None
        ):
            raise ValueError(
                "provide either transformer "
                "or query_transformer, not both"
            )

        self.retriever = retriever
        self.transformer = (
            transformer
            or query_transformer
            or HeuristicQueryTransformer()
        )
        self.grader = (
            grader
            or HeuristicEvidenceGrader()
        )

    async def retrieve(
        self,
        query: str,
        *,
        user_id: int,
        top_k: int = 5,
        max_rounds: int = 3,
        enable_query_rewrite: bool = True,
        enable_multi_query: bool = False,
        enable_decomposition: bool = False,
    ) -> AgenticRetrievalResult:
        original_query = _normalize_text(query)

        if not original_query:
            raise ValueError(
                "query must not be empty"
            )

        effective_top_k = max(
            1,
            int(top_k),
        )

        effective_max_rounds = max(
            1,
            int(max_rounds),
        )

        # 用户知识库隔离 Contract。
        filters = {
            "userId": user_id,
        }

        rounds: list[
            AgenticRetrievalRound
        ] = []

        accumulated_hits: list[
            RetrievalHit
        ] = []

        final_grade = EvidenceGrade(
            relevance=0.0,
            coverage=0.0,
            confidence=0.95,
            sufficient=False,
            reason="retrieval not started",
        )

        for round_index in range(
            effective_max_rounds
        ):
            round_query = original_query

            previous_round = (
                rounds[-1]
                if rounds
                else None
            )

            # ----------------------------------------------------
            # 1. Query Rewrite
            # ----------------------------------------------------
            if enable_query_rewrite:
                rewritten = (
                    await self
                    .transformer
                    .rewrite(
                        original_query,
                        round_index=round_index,
                        previous_query=(
                            previous_round.query
                            if previous_round
                            is not None
                            else None
                        ),
                        feedback=(
                            previous_round.grade.reason
                            if previous_round
                            is not None
                            else None
                        ),
                    )
                )

                rewritten = _normalize_text(
                    rewritten
                )

                if rewritten:
                    round_query = rewritten

            # ----------------------------------------------------
            # 2. Build Retrieval Queries
            # ----------------------------------------------------
            candidate_queries: list[str] = [
                round_query
            ]

            if enable_multi_query:
                candidate_queries.extend(
                    await self
                    .transformer
                    .multi_query(
                        round_query
                    )
                )

            if enable_decomposition:
                candidate_queries.extend(
                    await self
                    .transformer
                    .decompose(
                        round_query
                    )
                )

            candidate_queries = (
                _deduplicate_texts(
                    candidate_queries
                )
            )

            if not candidate_queries:
                candidate_queries = [
                    round_query
                ]

            # ----------------------------------------------------
            # 3. Parallel Retrieval Contract
            # ----------------------------------------------------
            retrieved_groups = await asyncio.gather(
                *[
                    self.retriever.retrieve(
                        candidate_query,
                        top_k=effective_top_k,
                        filters=filters,
                    )
                    for candidate_query
                    in candidate_queries
                ]
            )

            current_round_hits: list[
                RetrievalHit
            ] = []

            for group in retrieved_groups:
                current_round_hits.extend(
                    list(group)
                )

            # ----------------------------------------------------
            # 4. Cross-query / Cross-round Deduplication
            # ----------------------------------------------------
            accumulated_hits = (
                self._merge_hits(
                    accumulated_hits,
                    current_round_hits,
                    top_k=effective_top_k,
                )
            )

            # ----------------------------------------------------
            # 5. Evidence Grade
            # ----------------------------------------------------
            final_grade = (
                await self
                .grader
                .grade(
                    original_query,
                    accumulated_hits,
                )
            )

            rounds.append(
                AgenticRetrievalRound(
                    round_index=round_index,
                    query=round_query,
                    queries=list(
                        candidate_queries
                    ),
                    hits=list(
                        accumulated_hits
                    ),
                    grade=final_grade,
                )
            )

            # ----------------------------------------------------
            # 6. Agentic Stop Condition
            # ----------------------------------------------------
            if final_grade.sufficient:
                return (
                    AgenticRetrievalResult(
                        query=original_query,
                        hits=list(
                            accumulated_hits
                        ),
                        rounds=rounds,
                        grade=final_grade,
                        sufficient=True,
                        stopped_reason=(
                            "evidence_sufficient"
                        ),
                    )
                )

        # --------------------------------------------------------
        # max_rounds exhausted
        # --------------------------------------------------------
        return AgenticRetrievalResult(
            query=original_query,
            hits=list(
                accumulated_hits
            ),
            rounds=rounds,
            grade=final_grade,
            sufficient=False,
            stopped_reason=(
                "max_rounds_reached"
            ),
        )

    @staticmethod
    def _merge_hits(
        existing: Sequence[RetrievalHit],
        incoming: Sequence[RetrievalHit],
        *,
        top_k: int,
    ) -> list[RetrievalHit]:
        """
        Deduplicate by document.id.

        When one document is hit by multiple queries,
        retain the hit with the higher retrieval score.
        """

        best_by_document: dict[
            str,
            RetrievalHit,
        ] = {}

        anonymous_counter = 0

        for hit in [
            *existing,
            *incoming,
        ]:
            document = getattr(
                hit,
                "document",
                None,
            )

            document_id = getattr(
                document,
                "id",
                None,
            )

            if (
                document_id is None
                or not str(
                    document_id
                ).strip()
            ):
                anonymous_counter += 1
                key = (
                    "__anonymous__:"
                    f"{anonymous_counter}"
                )
            else:
                key = str(
                    document_id
                )

            previous = (
                best_by_document
                .get(
                    key
                )
            )

            if (
                previous is None
                or _safe_hit_score(
                    hit
                )
                > _safe_hit_score(
                    previous
                )
            ):
                best_by_document[
                    key
                ] = hit

        merged = sorted(
            best_by_document.values(),
            key=_safe_hit_score,
            reverse=True,
        )

        return merged[
            :max(
                1,
                int(top_k),
            )
        ]


__all__ = [
    "QueryTransformer",
    "HeuristicQueryTransformer",
    "EvidenceGrade",
    "EvidenceGrader",
    "HeuristicEvidenceGrader",
    "AgenticRetrievalRound",
    "AgenticRetrievalResult",
    "AgenticRetrievalExecutor",
]
