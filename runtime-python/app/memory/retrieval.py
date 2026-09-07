from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import httpx

from app.memory.long_term import MemoryCandidateDetector
from app.rag.embedding import EmbeddingProvider


MemoryRetrievalStatus = Literal[
    "completed",
    "skipped",
    "error",
]


_MEMORY_OVERVIEW_MARKERS = (
    "你记得我",
    "你还记得我",
    "记得我什么",
    "关于我的记忆",
    "我的偏好",
    "我的习惯",
    "之前告诉你",
    "what do you remember",
    "remember about me",
    "my preferences",
)


def is_memory_overview_query(text: str) -> bool:
    """Return True when the user is asking AgentMesh about remembered user context.

    Memory-overview questions are epistemically special: answers must be grounded
    in Conversation Memory and/or User-global Long-term Memory, never inferred
    from Project Knowledge, RAG evidence, or generic model priors.
    """

    normalized = " ".join(text.strip().lower().split())
    if not normalized:
        return False
    return any(marker in normalized for marker in _MEMORY_OVERVIEW_MARKERS)


@dataclass(frozen=True, slots=True)
class UserLongTermMemory:
    id: int
    user_id: int
    category: str
    memory_key: str
    content: str
    source_type: str
    confidence: float
    status: str = "active"
    last_accessed_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True, slots=True)
class RetrievedLongTermMemory:
    memory: UserLongTermMemory
    score: float
    semantic_score: float
    lexical_score: float
    relevance_score: float
    authority_score: float


@dataclass(frozen=True, slots=True)
class LongTermMemoryRetrievalOutcome:
    status: MemoryRetrievalStatus
    reason: str
    candidate_count: int = 0
    unsafe_skipped_count: int = 0
    semantic_used: bool = False
    memories: tuple[RetrievedLongTermMemory, ...] = field(default_factory=tuple)

    def trace_detail(self) -> dict[str, Any]:
        return {
            "reason": self.reason,
            "candidateCount": self.candidate_count,
            "selectedCount": len(self.memories),
            "unsafeSkippedCount": self.unsafe_skipped_count,
            "semanticUsed": self.semantic_used,
            "memories": [
                {
                    "memoryId": item.memory.id,
                    "memoryKey": item.memory.memory_key,
                    "category": item.memory.category,
                    "sourceType": item.memory.source_type,
                    "score": round(item.score, 6),
                }
                for item in self.memories
            ],
        }


class LongTermMemorySource(Protocol):
    async def list_active(
        self,
        *,
        user_id: int,
        limit: int,
    ) -> list[UserLongTermMemory]:
        ...


class LongTermMemoryRetriever(Protocol):
    async def retrieve(
        self,
        *,
        user_id: int,
        query: str,
    ) -> LongTermMemoryRetrievalOutcome:
        ...


class ControlPlaneLongTermMemorySource:
    """Read user-global memories through the Go ownership boundary.

    Python Runtime intentionally does not connect to MySQL directly.  The
    internal token protects the control-plane contract while user_id remains
    explicit, matching the P3.1 ownership model.
    """

    def __init__(
        self,
        *,
        internal_token: str,
        base_url: str | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        configured = (
            base_url
            or os.getenv("AGENTMESH_CONTROL_PLANE_URL")
            or "http://127.0.0.1:8086"
        )
        self.base_url = configured.rstrip("/")
        self.internal_token = internal_token
        self.timeout_seconds = timeout_seconds

    async def list_active(
        self,
        *,
        user_id: int,
        limit: int,
    ) -> list[UserLongTermMemory]:
        safe_limit = max(1, min(int(limit), 200))

        async with httpx.AsyncClient(
            timeout=self.timeout_seconds,
            trust_env=False,
        ) as client:
            response = await client.get(
                f"{self.base_url}/internal/v1/users/{user_id}/memories",
                headers={
                    "X-Internal-Token": self.internal_token,
                },
                params={
                    "limit": safe_limit,
                },
            )
            response.raise_for_status()
            payload = response.json()

        raw_data = payload.get("data", payload)
        if not isinstance(raw_data, list):
            raise ValueError("memory list response must contain a list")

        memories: list[UserLongTermMemory] = []
        for raw in raw_data:
            if not isinstance(raw, dict):
                continue

            try:
                memory_id = int(raw.get("id"))
                owner_id = int(raw.get("userId"))
                confidence = float(raw.get("confidence", 1.0))
            except (TypeError, ValueError):
                continue

            content = " ".join(str(raw.get("content", "")).strip().split())
            memory_key = str(raw.get("memoryKey", "")).strip().lower()
            category = str(raw.get("category", "other")).strip().lower()
            source_type = str(raw.get("sourceType", "inferred_user")).strip().lower()
            status = str(raw.get("status", "active")).strip().lower()

            if (
                memory_id <= 0
                or owner_id != user_id
                or not content
                or not memory_key
                or status != "active"
            ):
                continue

            memories.append(
                UserLongTermMemory(
                    id=memory_id,
                    user_id=owner_id,
                    category=category,
                    memory_key=memory_key,
                    content=content,
                    source_type=source_type,
                    confidence=max(0.0, min(confidence, 1.0)),
                    status=status,
                    last_accessed_at=_optional_string(raw.get("lastAccessedAt")),
                    created_at=_optional_string(raw.get("createdAt")),
                    updated_at=_optional_string(raw.get("updatedAt")),
                )
            )

        return memories


class HybridLongTermMemoryRetriever:
    """Query-dependent retrieval over user-global long-term memories.

    P3.3 deliberately separates *memory retrieval* from Project Knowledge RAG:

        user_id -> active user memories -> relevance ranking -> prompt context

    Project id is never part of this path.  Conversely, RAG evidence is never
    treated as memory.  The retriever also fails open: memory availability must
    not decide whether the main Agent task can execute.
    """

    _token_pattern = re.compile(r"[a-z0-9_]+|[\u4e00-\u9fff]")

    _coding_markers = (
        "代码",
        "编程",
        "开发",
        "java",
        "golang",
        " go ",
        "python",
        "typescript",
        "react",
        "spring",
    )
    _ui_markers = (
        "界面",
        "ui",
        "ux",
        "视觉",
        "布局",
        "前端",
    )
    _career_markers = (
        "岗位",
        "求职",
        "简历",
        "面试",
        "职业",
        "career",
        "job",
        "agent 开发",
        "agent开发",
    )
    _workflow_markers = (
        "流程",
        "步骤",
        "怎么做",
        "操作",
        "workflow",
        "process",
    )
    _memory_overview_markers = _MEMORY_OVERVIEW_MARKERS

    def __init__(
        self,
        *,
        source: LongTermMemorySource,
        embedding: EmbeddingProvider | None = None,
        enabled: bool = True,
        candidate_limit: int = 100,
        top_k: int = 6,
        min_score: float = 0.28,
        semantic_weight: float = 0.40,
        lexical_weight: float = 0.25,
        confidence_weight: float = 0.10,
        authority_weight: float = 0.10,
        relevance_weight: float = 0.15,
    ) -> None:
        self.source = source
        self.embedding = embedding
        self.enabled = enabled
        self.candidate_limit = max(1, min(int(candidate_limit), 200))
        self.top_k = max(1, min(int(top_k), 20))
        self.min_score = max(0.0, min(float(min_score), 1.0))
        self.detector = MemoryCandidateDetector()

        weights = [
            max(0.0, float(semantic_weight)),
            max(0.0, float(lexical_weight)),
            max(0.0, float(confidence_weight)),
            max(0.0, float(authority_weight)),
            max(0.0, float(relevance_weight)),
        ]
        total = sum(weights)
        if total <= 0:
            raise ValueError("memory retrieval weights cannot all be zero")

        (
            self.semantic_weight,
            self.lexical_weight,
            self.confidence_weight,
            self.authority_weight,
            self.relevance_weight,
        ) = tuple(value / total for value in weights)

    async def retrieve(
        self,
        *,
        user_id: int,
        query: str,
    ) -> LongTermMemoryRetrievalOutcome:
        normalized_query = " ".join(query.strip().split())

        if not self.enabled:
            return LongTermMemoryRetrievalOutcome(
                status="skipped",
                reason="disabled",
            )

        if user_id <= 0 or not normalized_query:
            return LongTermMemoryRetrievalOutcome(
                status="skipped",
                reason="invalid_request",
            )

        try:
            candidates = await self.source.list_active(
                user_id=user_id,
                limit=self.candidate_limit,
            )
        except Exception as exc:
            return LongTermMemoryRetrievalOutcome(
                status="error",
                reason=f"control_plane_read_failed:{type(exc).__name__}",
            )

        if not candidates:
            return LongTermMemoryRetrievalOutcome(
                status="completed",
                reason="no_active_memories",
            )

        safe_candidates: list[UserLongTermMemory] = []
        unsafe_skipped = 0

        for memory in candidates:
            rejection = self.detector.safety_rejection_reason(memory.content)
            if rejection:
                unsafe_skipped += 1
                continue

            if memory.memory_key.startswith(
                (
                    "project.",
                    "knowledge.",
                    "rag.",
                    "tool.",
                    "mcp.",
                    "secret.",
                )
            ):
                unsafe_skipped += 1
                continue

            safe_candidates.append(memory)

        if not safe_candidates:
            return LongTermMemoryRetrievalOutcome(
                status="completed",
                reason="no_safe_memories",
                candidate_count=len(candidates),
                unsafe_skipped_count=unsafe_skipped,
            )

        semantic_scores = [0.0 for _ in safe_candidates]
        semantic_used = False

        if self.embedding is not None:
            try:
                vectors = await self.embedding.embed(
                    [normalized_query]
                    + [self._embedding_text(memory) for memory in safe_candidates]
                )
                if len(vectors) != len(safe_candidates) + 1:
                    raise ValueError("memory embedding count mismatch")

                query_vector = vectors[0]
                semantic_scores = [
                    self._cosine_similarity(query_vector, vector)
                    for vector in vectors[1:]
                ]
                semantic_used = True
            except Exception:
                # Semantic retrieval is an optional quality layer.  Lexical,
                # confidence, authority and domain signals remain available.
                semantic_scores = [0.0 for _ in safe_candidates]
                semantic_used = False

        ranked: list[RetrievedLongTermMemory] = []
        for memory, semantic_score in zip(
            safe_candidates,
            semantic_scores,
            strict=True,
        ):
            lexical_score = self._lexical_score(
                normalized_query,
                memory,
            )
            relevance_score = self._relevance_score(
                normalized_query,
                memory,
                lexical_score=lexical_score,
            )
            authority_score = self._authority_score(memory.source_type)

            score = (
                self.semantic_weight * semantic_score
                + self.lexical_weight * lexical_score
                + self.confidence_weight * memory.confidence
                + self.authority_weight * authority_score
                + self.relevance_weight * relevance_score
            )

            if score < self.min_score:
                continue

            ranked.append(
                RetrievedLongTermMemory(
                    memory=memory,
                    score=score,
                    semantic_score=semantic_score,
                    lexical_score=lexical_score,
                    relevance_score=relevance_score,
                    authority_score=authority_score,
                )
            )

        ranked.sort(
            key=lambda item: (
                -item.score,
                -item.memory.confidence,
                item.memory.id,
            )
        )
        selected = tuple(ranked[: self.top_k])

        reason = "memories_retrieved"
        if not selected:
            reason = "no_relevant_memories"
        elif not semantic_used and self.embedding is not None:
            reason = "memories_retrieved_lexical_fallback"

        return LongTermMemoryRetrievalOutcome(
            status="completed",
            reason=reason,
            candidate_count=len(candidates),
            unsafe_skipped_count=unsafe_skipped,
            semantic_used=semantic_used,
            memories=selected,
        )

    async def aclose(self) -> None:
        if self.embedding is None:
            return

        close_embedding = getattr(self.embedding, "aclose", None)
        if close_embedding is not None:
            await close_embedding()

    @classmethod
    def _tokens(cls, text: str) -> list[str]:
        return cls._token_pattern.findall(text.lower())

    @classmethod
    def _lexical_score(
        cls,
        query: str,
        memory: UserLongTermMemory,
    ) -> float:
        query_tokens = set(cls._tokens(query))
        memory_tokens = set(
            cls._tokens(
                memory.memory_key.replace(".", " ")
                + " "
                + memory.content
            )
        )

        if not query_tokens or not memory_tokens:
            return 0.0

        overlap = query_tokens & memory_tokens
        query_coverage = len(overlap) / len(query_tokens)
        union = query_tokens | memory_tokens
        jaccard = len(overlap) / len(union) if union else 0.0

        return max(
            0.0,
            min(1.0, 0.7 * query_coverage + 0.3 * jaccard),
        )

    @classmethod
    def _relevance_score(
        cls,
        query: str,
        memory: UserLongTermMemory,
        *,
        lexical_score: float,
    ) -> float:
        lower = f" {query.lower()} "
        key = memory.memory_key
        score = 0.0

        if any(marker in lower for marker in cls._memory_overview_markers):
            return 1.0

        # Language preference is an ambient user preference that can affect any
        # generated response even when the current query contains no word such
        # as “language” or “中文”.
        if key == "preference.response_language":
            score = 1.0
        elif key.startswith("preference.coding."):
            if any(marker in lower for marker in cls._coding_markers):
                score = 1.0
        elif key.startswith("preference.ui."):
            if any(marker in lower for marker in cls._ui_markers):
                score = 1.0
        elif memory.category == "goal":
            if any(marker in lower for marker in cls._career_markers):
                score = 1.0
        elif memory.category == "workflow":
            if any(marker in lower for marker in cls._workflow_markers):
                score = 0.8
        elif memory.category == "profile":
            if any(marker in lower for marker in ("我", "我的", "自己", "about me")):
                score = 0.6

        if lexical_score >= 0.35:
            score = max(score, 0.6)
        elif lexical_score >= 0.15:
            score = max(score, 0.3)

        if memory.category == "preference" and memory.source_type in {
            "manual",
            "explicit_user",
        }:
            score = max(score, 0.15)

        return max(0.0, min(score, 1.0))

    @staticmethod
    def _authority_score(source_type: str) -> float:
        normalized = source_type.strip().lower()
        return {
            "manual": 1.0,
            "explicit_user": 0.95,
            "inferred_user": 0.75,
        }.get(normalized, 0.6)

    @staticmethod
    def _embedding_text(memory: UserLongTermMemory) -> str:
        return (
            memory.memory_key.replace(".", " ")
            + "\n"
            + memory.category
            + "\n"
            + memory.content
        )

    @staticmethod
    def _cosine_similarity(left: list[float], right: list[float]) -> float:
        if not left or len(left) != len(right):
            return 0.0

        dot = sum(a * b for a, b in zip(left, right, strict=True))
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if left_norm <= 0 or right_norm <= 0:
            return 0.0

        cosine = dot / (left_norm * right_norm)
        return max(0.0, min(cosine, 1.0))


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
