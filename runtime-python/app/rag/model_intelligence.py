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
    ValidationError,
    field_validator,
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

    @field_validator(
        "relevance",
        "coverage",
        "confidence",
        mode="before",
    )
    @classmethod
    def _require_numeric_score(
        cls,
        value: Any,
    ) -> Any:
        if (
            isinstance(value, bool)
            or not isinstance(
                value,
                (int, float),
            )
        ):
            raise ValueError(
                "evidence score must be numeric"
            )

        return value

    @field_validator(
        "sufficient",
        mode="before",
    )
    @classmethod
    def _require_boolean_sufficient(
        cls,
        value: Any,
    ) -> Any:
        if type(value) is not bool:
            raise ValueError(
                "sufficient must be boolean"
            )

        return value


# ============================================================
# Structured Output Errors
# ============================================================


class StructuredOutputParseError(
    ValueError
):
    """Model output did not contain a parseable JSON object."""


class StructuredOutputSchemaError(
    ValueError
):
    """Parsed JSON did not satisfy the expected response schema."""


class StructuredOutputSemanticError(
    ValueError
):
    """Parsed JSON is valid but violates an operation-level semantic contract."""


class StructuredOutputProcessingError(
    ValueError
):
    """Unexpected local processing failure after a model response."""


# ============================================================
# JSON Parsing
#
# Real model output may wrap JSON in markdown fences or prose.
# Extraction therefore scans for the first *balanced* JSON object and
# understands quoted strings / escapes instead of using a greedy regex.
# ============================================================


def _balanced_object_end(
    text: str,
    start: int,
) -> int | None:
    depth = 0
    in_string = False
    escaped = False

    for index in range(
        start,
        len(text),
    ):
        char = text[index]

        if in_string:
            if escaped:
                escaped = False
                continue

            if char == "\\":
                escaped = True
                continue

            if char == '"':
                in_string = False

            continue

        if char == '"':
            in_string = True
            continue

        if char == "{":
            depth += 1
            continue

        if char == "}":
            depth -= 1

            if depth == 0:
                return index

            if depth < 0:
                return None

    return None


def _looks_like_json_object_start(
    text: str,
    start: int,
) -> bool:
    """
    Return whether ``text[start:]`` begins like a JSON object.

    JSON object members must start with a quoted key (or the object may be
    empty).  This lets the extractor distinguish a structured-output
    candidate such as ``{"key": ...}`` from incidental prose braces such
    as ``{example}``.
    """
    index = start + 1

    while (
        index < len(text)
        and text[index].isspace()
    ):
        index += 1

    if index >= len(text):
        return True

    return text[index] in {"\"", "}"}


def _extract_json_object(
    content: str,
) -> dict[str, Any]:
    text = content.strip()

    if not text:
        raise StructuredOutputParseError(
            "model response is empty"
        )

    saw_object_start = False
    cursor = 0

    while cursor < len(text):
        start = text.find(
            "{",
            cursor,
        )

        if start < 0:
            break

        saw_object_start = True
        looks_structured = (
            _looks_like_json_object_start(
                text,
                start,
            )
        )
        end = _balanced_object_end(
            text,
            start,
        )

        if end is None:
            # A JSON-looking outer object that never closes is an invalid
            # structured response.  Do not keep scanning its nested braces
            # and accidentally promote a complete inner object to the
            # top-level payload.
            if looks_structured:
                raise StructuredOutputParseError(
                    (
                        "model response contains an "
                        "unterminated JSON object"
                    )
                )

            # Incidental prose can contain an unmatched non-JSON brace.
            # Move past that brace so a later independent JSON object can
            # still be discovered.
            cursor = start + 1
            continue

        candidate = text[
            start:
            end + 1
        ]

        try:
            payload = json.loads(
                candidate
            )
        except json.JSONDecodeError:
            # The whole balanced brace block is one candidate.  If it is
            # malformed, skip that complete block rather than scanning its
            # nested braces as separate top-level payloads.  A later
            # independent JSON object remains eligible.
            cursor = end + 1
            continue

        if isinstance(
            payload,
            dict,
        ):
            return payload

        cursor = end + 1

    if saw_object_start:
        raise StructuredOutputParseError(
            (
                "model response contains "
                "no parseable JSON object"
            )
        )

    raise StructuredOutputParseError(
        (
            "model response does not contain "
            "a JSON object"
        )
    )


def _validate_payload(
    schema: type[BaseModel],
    content: str,
) -> BaseModel:
    payload = _extract_json_object(
        content
    )

    try:
        return schema.model_validate(
            payload
        )
    except ValidationError as exc:
        raise StructuredOutputSchemaError(
            (
                "model JSON does not satisfy "
                f"{schema.__name__}: "
                f"{exc.errors(include_url=False)}"
            )[:1000]
        ) from exc


# ============================================================
# Structured Output Recovery
#
# Provider/network retry stays in ModelGateway. This layer only retries a
# successful model call whose text cannot satisfy the structured-output
# contract. It never repairs, guesses, or coerces malformed JSON.
# ============================================================


def _structured_output_error_class(
    exc: Exception,
) -> str:
    if isinstance(
        exc,
        StructuredOutputParseError,
    ):
        return "RESPONSE_PARSE_ERROR"

    if isinstance(
        exc,
        StructuredOutputSchemaError,
    ):
        return "RESPONSE_SCHEMA_ERROR"

    if isinstance(
        exc,
        StructuredOutputSemanticError,
    ):
        return "RESPONSE_SEMANTIC_ERROR"

    if isinstance(
        exc,
        StructuredOutputProcessingError,
    ):
        return "RESPONSE_PROCESSING_ERROR"

    return "RESPONSE_PROCESSING_ERROR"


def _structured_output_retry_prompt(
    prompt: str,
    *,
    error_class: str,
    error_detail: str | None = None,
) -> str:
    detail = " ".join(
        (error_detail or "").strip().split()
    )[:300]

    semantic_instruction = ""
    if error_class == "RESPONSE_SEMANTIC_ERROR":
        semantic_instruction = (
            "\nThe JSON syntax was valid, but the response violated the "
            "operation-level semantic contract. Correct that semantic "
            "violation while preserving the original retrieval intent."
        )

    detail_instruction = (
        f"\nValidation detail: {detail}"
        if detail
        else ""
    )

    return f"""
{prompt}

[structured-output retry]
The previous response was rejected as {error_class}.{semantic_instruction}{detail_instruction}
Return exactly ONE complete JSON object matching the Required JSON schema above.
Do not use markdown fences, comments, or explanatory prose.
Start with {{ and end with }}.
Close every string and object.
Include every required field with the exact required JSON type.
Keep free-text explanation fields short.
""".strip()


async def _generate_structured_payload(
    *,
    model: AgenticRAGModel,
    prompt: str,
    schema: type[BaseModel],
    on_model_event: (
        ModelEventHandler
        | None
    ),
    max_attempts: int,
    semantic_validator: (
        Callable[[BaseModel], None]
        | None
    ) = None,
) -> tuple[
    BaseModel,
    int,
    int,
    bool,
    str | None,
]:
    attempts_limit = max(
        1,
        int(max_attempts),
    )

    first_error_class: str | None = None
    current_prompt = prompt

    for attempt in range(
        1,
        attempts_limit + 1,
    ):
        content = await model.generate(
            current_prompt,
            on_model_event,
        )

        try:
            payload = _validate_payload(
                schema,
                content,
            )

            if semantic_validator is not None:
                semantic_validator(payload)
        except (
            StructuredOutputParseError,
            StructuredOutputSchemaError,
            StructuredOutputSemanticError,
        ) as exc:
            error_class = (
                _structured_output_error_class(
                    exc
                )
            )

            if first_error_class is None:
                first_error_class = error_class

            setattr(
                exc,
                "agentmesh_structured_output_attempts",
                attempt,
            )
            setattr(
                exc,
                "agentmesh_structured_output_retries",
                attempt - 1,
            )
            setattr(
                exc,
                "agentmesh_structured_output_first_error_type",
                first_error_class,
            )

            if attempt >= attempts_limit:
                raise

            current_prompt = (
                _structured_output_retry_prompt(
                    prompt,
                    error_class=error_class,
                    error_detail=str(exc),
                )
            )
            continue
        except Exception as exc:
            processing_error = StructuredOutputProcessingError(
                (
                    "structured output processing failed: "
                    f"{type(exc).__name__}: {str(exc)[:300]}"
                )
            )
            setattr(
                processing_error,
                "agentmesh_structured_output_attempts",
                attempt,
            )
            setattr(
                processing_error,
                "agentmesh_structured_output_retries",
                attempt - 1,
            )
            setattr(
                processing_error,
                "agentmesh_structured_output_first_error_type",
                (
                    first_error_class
                    or "RESPONSE_PROCESSING_ERROR"
                ),
            )
            raise processing_error from exc

        return (
            payload,
            attempt,
            attempt - 1,
            attempt > 1,
            first_error_class,
        )

    raise AssertionError(
        "unreachable structured-output recovery state"
    )

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
        structured_output_max_attempts: int = 3,
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

        self._structured_output_max_attempts = max(
            1,
            int(structured_output_max_attempts),
        )

    @staticmethod
    def _normalize_query_value(
        value: str,
    ) -> str:
        return " ".join(
            str(value).strip().split()
        )

    @classmethod
    def _validate_rewrite_payload(
        cls,
        payload: BaseModel,
        *,
        previous_query: str,
    ) -> None:
        if not isinstance(payload, _RewritePayload):
            raise StructuredOutputProcessingError(
                "rewrite validator received unexpected payload type"
            )

        result = cls._normalize_query_value(
            payload.query
        )

        if not result:
            raise StructuredOutputSemanticError(
                "rewritten query is empty after normalization"
            )

        if (
            previous_query
            and result.lower()
            == previous_query.lower()
        ):
            raise StructuredOutputSemanticError(
                (
                    "rewritten query duplicates previous "
                    "retrieval query"
                )
            )

    @staticmethod
    def _validate_queries_payload(
        payload: BaseModel,
        *,
        operation: str,
    ) -> None:
        if not isinstance(payload, _QueriesPayload):
            raise StructuredOutputProcessingError(
                f"{operation} validator received unexpected payload type"
            )

        queries = _deduplicate_strings(
            payload.queries,
            max_items=4,
        )

        if not queries:
            raise StructuredOutputSemanticError(
                f"model returned no usable {operation} queries"
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
            (
                payload,
                structured_attempts,
                structured_retries,
                structured_recovered,
                structured_recovery_error_type,
            ) = await _generate_structured_payload(
                model=self._model,
                prompt=prompt,
                schema=_RewritePayload,
                on_model_event=self._on_model_event,
                max_attempts=(
                    self._structured_output_max_attempts
                ),
                semantic_validator=(
                    lambda candidate: (
                        self._validate_rewrite_payload(
                            candidate,
                            previous_query=previous_query_text,
                        )
                    )
                ),
            )

            result = self._normalize_query_value(
                payload.query
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
                structuredOutputAttempts=(
                    structured_attempts
                ),
                structuredOutputRetries=(
                    structured_retries
                ),
                structuredOutputRecovered=(
                    structured_recovered
                ),
                structuredOutputRecoveryErrorType=(
                    structured_recovery_error_type
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
            (
                payload,
                structured_attempts,
                structured_retries,
                structured_recovered,
                structured_recovery_error_type,
            ) = await _generate_structured_payload(
                model=self._model,
                prompt=prompt,
                schema=_QueriesPayload,
                on_model_event=self._on_model_event,
                max_attempts=(
                    self._structured_output_max_attempts
                ),
                semantic_validator=(
                    lambda candidate: (
                        self._validate_queries_payload(
                            candidate,
                            operation="multi-query",
                        )
                    )
                ),
            )

            queries = (
                _deduplicate_strings(
                    payload.queries,
                    max_items=4,
                )
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
                structuredOutputAttempts=(
                    structured_attempts
                ),
                structuredOutputRetries=(
                    structured_retries
                ),
                structuredOutputRecovered=(
                    structured_recovered
                ),
                structuredOutputRecoveryErrorType=(
                    structured_recovery_error_type
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
            (
                payload,
                structured_attempts,
                structured_retries,
                structured_recovered,
                structured_recovery_error_type,
            ) = await _generate_structured_payload(
                model=self._model,
                prompt=prompt,
                schema=_QueriesPayload,
                on_model_event=self._on_model_event,
                max_attempts=(
                    self._structured_output_max_attempts
                ),
                semantic_validator=(
                    lambda candidate: (
                        self._validate_queries_payload(
                            candidate,
                            operation="decomposition",
                        )
                    )
                ),
            )

            queries = (
                _deduplicate_strings(
                    payload.queries,
                    max_items=4,
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
                structuredOutputAttempts=(
                    structured_attempts
                ),
                structuredOutputRetries=(
                    structured_retries
                ),
                structuredOutputRecovered=(
                    structured_recovered
                ),
                structuredOutputRecoveryErrorType=(
                    structured_recovery_error_type
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
            structuredOutputAttempts=(
                int(
                    getattr(
                        exc,
                        "agentmesh_structured_output_attempts",
                        1,
                    )
                )
            ),
            structuredOutputRetries=(
                int(
                    getattr(
                        exc,
                        "agentmesh_structured_output_retries",
                        0,
                    )
                )
            ),
            structuredOutputRecovered=False,
            structuredOutputRecoveryErrorType=(
                getattr(
                    exc,
                    "agentmesh_structured_output_first_error_type",
                    None,
                )
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
        structured_output_max_attempts: int = 3,
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

        self._structured_output_max_attempts = max(
            1,
            int(structured_output_max_attempts),
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

        requested_grader = (
            self._requested_grader_name()
        )

        try:
            (
                payload,
                structured_attempts,
                structured_retries,
                structured_recovered,
                structured_recovery_error_type,
            ) = await _generate_structured_payload(
                model=self._model,
                prompt=prompt,
                schema=_EvidencePayload,
                on_model_event=self._on_model_event,
                max_attempts=(
                    self._structured_output_max_attempts
                ),
            )
        except StructuredOutputParseError as exc:
            return await self._fallback_grade(
                query,
                hits,
                requested_grader=requested_grader,
                error_class=(
                    "RESPONSE_PARSE_ERROR"
                ),
                exc=exc,
            )
        except StructuredOutputSchemaError as exc:
            return await self._fallback_grade(
                query,
                hits,
                requested_grader=requested_grader,
                error_class=(
                    "RESPONSE_SCHEMA_ERROR"
                ),
                exc=exc,
            )
        except StructuredOutputProcessingError as exc:
            return await self._fallback_grade(
                query,
                hits,
                requested_grader=requested_grader,
                error_class=(
                    "RESPONSE_PROCESSING_ERROR"
                ),
                exc=exc,
            )
        except Exception as exc:
            return await self._fallback_grade(
                query,
                hits,
                requested_grader=requested_grader,
                error_class="PROVIDER_ERROR",
                exc=exc,
            )

        grade = EvidenceGrade(
            relevance=(
                round(
                    payload.relevance,
                    4,
                )
            ),
            coverage=(
                round(
                    payload.coverage,
                    4,
                )
            ),
            confidence=(
                round(
                    payload.confidence,
                    4,
                )
            ),
            sufficient=(
                payload.sufficient
            ),
            reason=(
                payload.reason
            ),
        )

        self._emit(
            "RAG Evidence Graded",
            backend="model",
            fallback=False,
            requestedEvidenceGrader=(
                requested_grader
            ),
            effectiveEvidenceGrader=(
                requested_grader
            ),
            evidenceGradeFallback=False,
            evidenceGradeStructuredAttempts=(
                structured_attempts
            ),
            evidenceGradeStructuredRetries=(
                structured_retries
            ),
            evidenceGradeStructuredRecovered=(
                structured_recovered
            ),
            evidenceGradeStructuredRecoveryErrorType=(
                structured_recovery_error_type
            ),
            relevance=grade.relevance,
            coverage=grade.coverage,
            confidence=grade.confidence,
            sufficient=grade.sufficient,
        )

        return grade

    def _requested_grader_name(
        self,
    ) -> str:
        value = (
            getattr(
                self._model,
                "model",
                None,
            )
            or getattr(
                self._model,
                "name",
                None,
            )
            or type(
                self._model
            ).__name__
        )

        return str(value)

    async def _fallback_grade(
        self,
        query: str,
        hits: Sequence[
            RetrievalHit
        ],
        *,
        requested_grader: str,
        error_class: str,
        exc: Exception,
    ) -> EvidenceGrade:
        fallback_grade = (
            await self
            ._fallback
            .grade(
                query,
                hits,
            )
        )

        error_message = str(exc)[:300]

        self._emit(
            (
                "RAG Evidence Grader "
                "Fallback"
            ),
            backend="heuristic",
            fallback=True,
            requestedEvidenceGrader=(
                requested_grader
            ),
            effectiveEvidenceGrader=(
                "heuristic"
            ),
            evidenceGradeFallback=True,
            evidenceGradeErrorType=(
                error_class
            ),
            evidenceGradeError=(
                error_message
            ),
            evidenceGradeStructuredAttempts=(
                int(
                    getattr(
                        exc,
                        "agentmesh_structured_output_attempts",
                        1,
                    )
                )
            ),
            evidenceGradeStructuredRetries=(
                int(
                    getattr(
                        exc,
                        "agentmesh_structured_output_retries",
                        0,
                    )
                )
            ),
            evidenceGradeStructuredRecovered=False,
            evidenceGradeStructuredRecoveryErrorType=(
                getattr(
                    exc,
                    "agentmesh_structured_output_first_error_type",
                    None,
                )
            ),
            # Backward-compatible fields consumed by existing traces.
            errorType=(
                type(exc).__name__
            ),
            error=error_message,
            sufficient=(
                fallback_grade.sufficient
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
