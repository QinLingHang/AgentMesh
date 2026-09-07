from __future__ import annotations

import json

from typing import (
    Any,
    Callable,
    Protocol,
    Sequence,
)

from pydantic import (
    BaseModel,
    Field,
)

from app.models.gateway import (
    ModelEventHandler,
)

from app.rag.agentic_retrieval import (
    EvidenceGrade,
    HeuristicEvidenceGrader,
    HeuristicQueryTransformer,
    QueryTransformer,
)

from app.rag.runtime import (
    RetrievalHit,
)


# ============================================================
# Model Contract
#
# This module does not depend directly on Qwen/OpenAI SDKs.
# It only depends on AgentMesh's model.default.generate(...)
# contract, so it can be reused by:
#
# - Qwen
# - OpenAI-compatible providers
# - Future BYOK providers
# ============================================================


class AgenticRAGModel(
    Protocol
):
    async def generate(
        self,
        prompt: str,
        on_event: (
            ModelEventHandler
            | None
        ) = None,
    ) -> str:
        ...


RAGIntelligenceEventHandler = (
    Callable[
        [dict[str, Any]],
        None,
    ]
)


# ============================================================
# Structured Output Schemas
# ============================================================


class _RewritePayload(
    BaseModel
):
    query: str = Field(
        min_length=1,
    )


class _QueriesPayload(
    BaseModel
):
    queries: list[str] = Field(
        min_length=1,
        max_length=8,
    )


class _EvidencePayload(
    BaseModel
):
    relevance: float = Field(
        ge=0.0,
        le=1.0,
    )

    coverage: float = Field(
        ge=0.0,
        le=1.0,
    )

    confidence: float = Field(
        ge=0.0,
        le=1.0,
    )

    sufficient: bool

    reason: str = ""


# ============================================================
# JSON Parsing
#
# Model output may be:
#
# ```json
# {...}
# ```
#
# or:
#
# explanation
# {...}
#
# so we extract the outer JSON object first.
# ============================================================


def _extract_json_object(
    content: str,
) -> dict[str, Any]:
    text = (
        content
        .strip()
    )

    start = text.find(
        "{"
    )

    end = text.rfind(
        "}"
    )

    if (
        start < 0
        or end < start
    ):
        raise ValueError(
            (
                "model response "
                "does not contain "
                "a JSON object"
            )
        )

    payload = json.loads(
        text[
            start:
            end + 1
        ]
    )

    if not isinstance(
        payload,
        dict,
    ):
        raise ValueError(
            "model JSON must be object"
        )

    return payload


def _deduplicate_strings(
    values: Sequence[str],
    *,
    max_items: int = 6,
) -> list[str]:
    output: list[str] = []

    seen: set[str] = set()

    for value in values:
        normalized = " ".join(
            str(
                value
            )
            .strip()
            .split()
        )

        if not normalized:
            continue

        key = (
            normalized
            .lower()
        )

        if key in seen:
            continue

        seen.add(
            key
        )

        output.append(
            normalized
        )

        if (
            len(
                output
            )
            >= max_items
        ):
            break

    return output


# ============================================================
# Model-backed Query Transformer
# ============================================================


class ModelBackedQueryTransformer(
    QueryTransformer
):
    """
    LLM handles Query Intelligence.

    AgenticRetrievalExecutor remains a deterministic controller.

    Model-backed responsibilities:
    - rewrite
    - multi-query
    - decomposition

    Model failure:
    - falls back to HeuristicQueryTransformer
    """

    def __init__(
        self,
        *,
        model: AgenticRAGModel,
        fallback: (
            QueryTransformer
            | None
        ) = None,
        on_model_event: (
            ModelEventHandler
            | None
        ) = None,
        on_rag_event: (
            RAGIntelligenceEventHandler
            | None
        ) = None,
    ) -> None:
        self._model = model

        self._fallback = (
            fallback
            or HeuristicQueryTransformer()
        )

        self._on_model_event = (
            on_model_event
        )

        self._on_rag_event = (
            on_rag_event
        )

    # ========================================================
    # Rewrite
    # ========================================================

    async def rewrite(
        self,
        query: str,
        *,
        round_index: int,
        previous_query: str | None = None,
        feedback: str | None = None,
    ) -> str:
        previous_query_text = (
            " ".join(
                (
                    previous_query
                    or ""
                )
                .strip()
                .split()
            )
        )

        feedback_text = (
            " ".join(
                (
                    feedback
                    or ""
                )
                .strip()
                .split()
            )
        )

        prompt = f"""
You are the query rewriting component of an Agentic RAG system.

[operation]
rewrite

[original user query]
{query}

[retrieval round]
{round_index + 1}

[previous retrieval query]
{previous_query_text or "(none)"}

[previous evidence assessment]
{feedback_text or "(none)"}

Rewrite the query for better knowledge retrieval.

Rules:
1. Preserve important entities, IDs, product names and exact technical terms.
2. Do NOT answer the user's question.
3. Improve retrieval intent and semantic clarity.
4. Do NOT invent implementation details, algorithms, configuration names,
   state names, retry policies, timeout values, or recovery mechanisms
   that are not explicitly present in the original query or previous
   evidence assessment.
5. If this is a later retrieval round, identify the information gaps
   explicitly mentioned by the previous evidence assessment.
6. Target only the missing aspects. Do not speculate about how those
   missing aspects might be implemented.
7. Prefer a concise retrieval query containing the original entity and
   2 to 4 missing concepts.
8. When previous evidence was insufficient, produce a meaningfully
   different retrieval query from the previous retrieval query.
9. Do not merely append a round number.
10. Do not include examples such as "e.g." or "for example".
11. Keep the rewritten retrieval query concise, preferably below 30 words.
12. Return JSON only.

Required JSON:
{{
  "query": "rewritten retrieval query"
}}
""".strip()

        try:
            content = (
                await self
                ._model
                .generate(
                    prompt,
                    self._on_model_event,
                )
            )

            payload = (
                _RewritePayload
                .model_validate(
                    _extract_json_object(
                        content
                    )
                )
            )

            result = " ".join(
                payload
                .query
                .strip()
                .split()
            )

            if not result:
                raise ValueError(
                    "empty rewritten query"
                )

            # Retry Diversity Guard:
            # prompt is a soft constraint; this is the hard guard.
            if (
                previous_query_text
                and result.lower()
                == previous_query_text.lower()
            ):
                raise ValueError(
                    (
                        "rewritten query "
                        "duplicates previous "
                        "retrieval query"
                    )
                )

            self._emit(
                "RAG Query Rewrite",
                operation="rewrite",
                backend="model",
                fallback=False,
                round=(
                    round_index
                    + 1
                ),
                feedbackAware=(
                    bool(
                        feedback_text
                    )
                ),
            )

            return result

        except Exception as exc:
            self._emit_fallback(
                operation="rewrite",
                exc=exc,
            )

            return await self._rewrite_with_fallback(
                query,
                round_index=round_index,
                previous_query=previous_query,
                feedback=feedback,
            )

    async def _rewrite_with_fallback(
        self,
        query: str,
        *,
        round_index: int,
        previous_query: str | None,
        feedback: str | None,
    ) -> str:
        """
        Backward-compatible fallback call.

        New QueryTransformer accepts previous_query/feedback, but older
        custom test fakes or plugins may still expose the old signature.
        """
        try:
            return (
                await self
                ._fallback
                .rewrite(
                    query,
                    round_index=round_index,
                    previous_query=previous_query,
                    feedback=feedback,
                )
            )
        except TypeError as exc:
            message = str(
                exc
            )

            compatibility_error = (
                "unexpected keyword argument"
                in message
                and (
                    "previous_query"
                    in message
                    or "feedback"
                    in message
                )
            )

            if not compatibility_error:
                raise

            return (
                await self
                ._fallback
                .rewrite(
                    query,
                    round_index=round_index,
                )
            )

    # ========================================================
    # Multi Query
    # ========================================================

    async def multi_query(
        self,
        query: str,
    ) -> list[str]:
        prompt = f"""
You are the multi-query planner of an Agentic RAG system.

[operation]
multi_query

[original query]
{query}

Generate 2 to 4 complementary retrieval queries.

Goals:
- improve recall
- use different semantic perspectives
- preserve important entities and exact technical terms
- do NOT answer the question
- do NOT invent facts

Return JSON only.

Required JSON:
{{
  "queries": [
    "query 1",
    "query 2",
    "query 3"
  ]
}}
""".strip()

        try:
            content = (
                await self
                ._model
                .generate(
                    prompt,
                    self._on_model_event,
                )
            )

            payload = (
                _QueriesPayload
                .model_validate(
                    _extract_json_object(
                        content
                    )
                )
            )

            queries = (
                _deduplicate_strings(
                    payload.queries,
                    max_items=4,
                )
            )

            if not queries:
                raise ValueError(
                    "model returned no queries"
                )

            self._emit(
                "RAG Multi Query Generated",
                operation="multi_query",
                backend="model",
                fallback=False,
                queryCount=(
                    len(
                        queries
                    )
                ),
            )

            return queries

        except Exception as exc:
            self._emit_fallback(
                operation=(
                    "multi_query"
                ),
                exc=exc,
            )

            return (
                await self
                ._fallback
                .multi_query(
                    query
                )
            )

    # ========================================================
    # Decomposition
    # ========================================================

    async def decompose(
        self,
        query: str,
    ) -> list[str]:
        prompt = f"""
You are the query decomposition component of an Agentic RAG system.

[operation]
decompose

[original query]
{query}

Decompose the question into 2 to 4 atomic retrieval sub-questions
when decomposition is useful.

Rules:
1. Each sub-question should retrieve one clear piece of evidence.
2. Preserve important entities and technical terms.
3. Do NOT answer any sub-question.
4. Avoid redundant sub-questions.
5. Return JSON only.

Required JSON:
{{
  "queries": [
    "sub-question 1",
    "sub-question 2"
  ]
}}
""".strip()

        try:
            content = (
                await self
                ._model
                .generate(
                    prompt,
                    self._on_model_event,
                )
            )

            payload = (
                _QueriesPayload
                .model_validate(
                    _extract_json_object(
                        content
                    )
                )
            )

            queries = (
                _deduplicate_strings(
                    payload.queries,
                    max_items=4,
                )
            )

            if not queries:
                raise ValueError(
                    (
                        "model returned no "
                        "decomposition queries"
                    )
                )

            self._emit(
                "RAG Query Decomposed",
                operation="decompose",
                backend="model",
                fallback=False,
                queryCount=(
                    len(
                        queries
                    )
                ),
            )

            return queries

        except Exception as exc:
            self._emit_fallback(
                operation="decompose",
                exc=exc,
            )

            return (
                await self
                ._fallback
                .decompose(
                    query
                )
            )

    # ========================================================
    # Events
    # ========================================================

    def _emit(
        self,
        title: str,
        **detail: Any,
    ) -> None:
        if (
            self._on_rag_event
            is None
        ):
            return

        self._on_rag_event(
            {
                "title":
                    title,

                "status":
                    "completed",

                **detail,
            }
        )

    def _emit_fallback(
        self,
        *,
        operation: str,
        exc: Exception,
    ) -> None:
        self._emit(
            (
                "RAG Query Intelligence "
                "Fallback"
            ),
            operation=operation,
            backend="heuristic",
            fallback=True,
            errorType=(
                type(
                    exc
                ).__name__
            ),
            error=(
                str(
                    exc
                )[:300]
            ),
        )


# ============================================================
# Model-backed Evidence Grader
# ============================================================


class ModelBackedEvidenceGrader:
    """
    Judge whether current retrieval evidence is relevant and sufficient.

    It does not answer the user's question and must only judge supplied
    evidence.
    """

    def __init__(
        self,
        *,
        model: AgenticRAGModel,
        fallback: (
            HeuristicEvidenceGrader
            | None
        ) = None,
        on_model_event: (
            ModelEventHandler
            | None
        ) = None,
        on_rag_event: (
            RAGIntelligenceEventHandler
            | None
        ) = None,
        max_documents: int = 6,
        max_chars_per_document: int = 1200,
    ) -> None:
        self._model = model

        self._fallback = (
            fallback
            or HeuristicEvidenceGrader()
        )

        self._on_model_event = (
            on_model_event
        )

        self._on_rag_event = (
            on_rag_event
        )

        self._max_documents = max(
            1,
            max_documents,
        )

        self._max_chars = max(
            200,
            max_chars_per_document,
        )

    async def grade(
        self,
        query: str,
        hits: Sequence[
            RetrievalHit
        ],
    ) -> EvidenceGrade:
        if not hits:
            # Empty evidence does not need an LLM call.
            return (
                await self
                ._fallback
                .grade(
                    query,
                    hits,
                )
            )

        evidence = []

        for hit in (
            hits[
                :self._max_documents
            ]
        ):
            evidence.append(
                {
                    "id":
                        hit.document.id,

                    "source":
                        hit.document.source,

                    "retrievalScore":
                        float(
                            hit.score
                        ),

                    "text":
                        hit
                        .document
                        .text[
                            :self._max_chars
                        ],
                }
            )

        prompt = f"""
You are the evidence grader of an Agentic RAG system.

[question]
{query}

[evidence]
{json.dumps(
    evidence,
    ensure_ascii=False,
)}

Judge ONLY the supplied evidence.
Do not answer the question.
Do not use external knowledge.

Score:
- relevance: how relevant the evidence is to the question
- coverage: how much of the question is covered
- confidence: confidence in this grading
- sufficient: true only if the available evidence is sufficient
  to support a grounded answer

All scores must be between 0 and 1.

Return JSON only.

Required JSON:
{{
  "relevance": 0.0,
  "coverage": 0.0,
  "confidence": 0.0,
  "sufficient": false,
  "reason": "short explanation"
}}
""".strip()

        try:
            content = (
                await self
                ._model
                .generate(
                    prompt,
                    self._on_model_event,
                )
            )

            payload = (
                _EvidencePayload
                .model_validate(
                    _extract_json_object(
                        content
                    )
                )
            )

            grade = EvidenceGrade(
                relevance=(
                    round(
                        payload
                        .relevance,
                        4,
                    )
                ),

                coverage=(
                    round(
                        payload
                        .coverage,
                        4,
                    )
                ),

                confidence=(
                    round(
                        payload
                        .confidence,
                        4,
                    )
                ),

                sufficient=(
                    payload
                    .sufficient
                ),

                reason=(
                    payload
                    .reason
                ),
            )

            self._emit(
                "RAG Evidence Graded",
                backend="model",
                fallback=False,
                relevance=(
                    grade.relevance
                ),
                coverage=(
                    grade.coverage
                ),
                confidence=(
                    grade.confidence
                ),
                sufficient=(
                    grade.sufficient
                ),
            )

            return grade

        except Exception as exc:
            fallback_grade = (
                await self
                ._fallback
                .grade(
                    query,
                    hits,
                )
            )

            self._emit(
                (
                    "RAG Evidence Grader "
                    "Fallback"
                ),
                backend="heuristic",
                fallback=True,
                errorType=(
                    type(
                        exc
                    ).__name__
                ),
                error=(
                    str(
                        exc
                    )[:300]
                ),
                sufficient=(
                    fallback_grade
                    .sufficient
                ),
            )

            return fallback_grade

    def _emit(
        self,
        title: str,
        **detail: Any,
    ) -> None:
        if (
            self._on_rag_event
            is None
        ):
            return

        self._on_rag_event(
            {
                "title":
                    title,

                "status":
                    "completed",

                **detail,
            }
        )


__all__ = [
    "AgenticRAGModel",
    "ModelBackedQueryTransformer",
    "ModelBackedEvidenceGrader",
]
