from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import httpx

from app.memory.retrieval import LongTermMemoryRetriever, RetrievedLongTermMemory


MemoryForgetStatus = Literal["completed", "skipped", "error"]


@dataclass(frozen=True, slots=True)
class MemoryForgetDecision:
    requested: bool
    query: str = ""
    reason: str = ""


@dataclass(frozen=True, slots=True)
class MemoryForgetRecord:
    memory_id: int
    memory_key: str
    category: str


@dataclass(frozen=True, slots=True)
class MemoryForgetOutcome:
    status: MemoryForgetStatus
    reason: str
    requested: bool = False
    records: tuple[MemoryForgetRecord, ...] = field(default_factory=tuple)

    def trace_detail(self) -> dict[str, Any]:
        return {
            "reason": self.reason,
            "requested": self.requested,
            "deletedCount": len(self.records),
            "deletes": [
                {
                    "memoryId": record.memory_id,
                    "memoryKey": record.memory_key,
                    "category": record.category,
                }
                for record in self.records
            ],
        }


class LongTermMemoryDeleteSink(Protocol):
    async def delete(self, *, user_id: int, memory_id: int) -> None:
        ...


class MemoryForgetDetector:
    """Conservative detector for explicit user-directed forget requests.

    The detector intentionally does not treat generic phrases such as
    "忘记密码怎么办" as a memory command.  A forget request must refer to the
    user's remembered context (我/我的/关于我/之前告诉你的...) or explicitly ask
    AgentMesh not to remember something anymore.
    """

    _prefix_patterns = (
        re.compile(
            r"^\s*(?:请|帮我)?(?:忘记|忘掉)"
            r"(?:我(?:之前|刚才|曾经)?(?:说过|告诉你|提过)?的?|我对|我的|关于我(?:的)?)\s*",
            re.I,
        ),
        re.compile(r"^\s*(?:别|不要)再记(?:得|住)?\s*", re.I),
        re.compile(
            r"^\s*(?:please\s+)?forget(?:\s+what\s+i\s+(?:told|said)|\s+about\s+me|\s+my|\s+that\s+i)\s*",
            re.I,
        ),
    )

    _generic_queries = {
        "",
        "这个",
        "这个偏好",
        "这项",
        "这项偏好",
        "那条",
        "那条偏好",
        "刚才那个",
        "刚才那个偏好",
        "偏好",
        "信息",
        "it",
        "that",
        "this",
    }

    def detect(self, text: str) -> MemoryForgetDecision:
        normalized = " ".join(text.strip().split())
        if not normalized:
            return MemoryForgetDecision(False, reason="empty")

        for pattern in self._prefix_patterns:
            match = pattern.search(normalized)
            if not match:
                continue

            query = normalized[match.end():].strip(" ，,。.!！？?:：")
            lowered = query.lower()
            if lowered in self._generic_queries or len(query) < 2:
                return MemoryForgetDecision(
                    True,
                    query=query,
                    reason="need_more_specific_request",
                )

            return MemoryForgetDecision(
                True,
                query=query,
                reason="explicit_forget_request",
            )

        return MemoryForgetDecision(False, reason="not_forget_request")


class ControlPlaneLongTermMemoryDeleteSink:
    """Delete user-owned memory through the Go control-plane boundary."""

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

    async def delete(self, *, user_id: int, memory_id: int) -> None:
        async with httpx.AsyncClient(
            timeout=self.timeout_seconds,
            trust_env=False,
        ) as client:
            response = await client.delete(
                f"{self.base_url}/internal/v1/users/{user_id}/memories/{memory_id}",
                headers={"X-Internal-Token": self.internal_token},
            )
            response.raise_for_status()


class AutomaticLongTermMemoryForgetter:
    """Resolve an explicit forget request to at most one durable memory.

    Deletion is intentionally conservative.  If ranking is ambiguous, nothing
    is deleted and the user is asked to be more specific.  This is safer than
    a broad "delete all matching" policy for an implicit conversational UI.
    """

    def __init__(
        self,
        *,
        retriever: LongTermMemoryRetriever,
        sink: LongTermMemoryDeleteSink,
        detector: MemoryForgetDetector | None = None,
        ambiguity_margin: float = 0.05,
    ) -> None:
        self.retriever = retriever
        self.sink = sink
        self.detector = detector or MemoryForgetDetector()
        self.ambiguity_margin = max(0.0, float(ambiguity_margin))

    async def process(self, *, user_id: int, text: str) -> MemoryForgetOutcome:
        decision = self.detector.detect(text)
        if not decision.requested:
            return MemoryForgetOutcome(
                status="skipped",
                reason=decision.reason,
                requested=False,
            )

        if decision.reason == "need_more_specific_request":
            return MemoryForgetOutcome(
                status="completed",
                reason=decision.reason,
                requested=True,
            )

        try:
            retrieval = await self.retriever.retrieve(
                user_id=user_id,
                query=decision.query,
            )
        except Exception as exc:
            return MemoryForgetOutcome(
                status="error",
                reason=f"forget_retrieval_failed:{type(exc).__name__}",
                requested=True,
            )

        ranked = list(retrieval.memories)
        if not ranked:
            return MemoryForgetOutcome(
                status="completed",
                reason="no_matching_memory",
                requested=True,
            )

        if self._is_ambiguous(ranked):
            return MemoryForgetOutcome(
                status="completed",
                reason="ambiguous_memory_match",
                requested=True,
            )

        target = ranked[0].memory
        try:
            await self.sink.delete(
                user_id=user_id,
                memory_id=target.id,
            )
        except Exception as exc:
            return MemoryForgetOutcome(
                status="error",
                reason=f"control_plane_delete_failed:{type(exc).__name__}",
                requested=True,
            )

        return MemoryForgetOutcome(
            status="completed",
            reason="memory_forgotten",
            requested=True,
            records=(
                MemoryForgetRecord(
                    memory_id=target.id,
                    memory_key=target.memory_key,
                    category=target.category,
                ),
            ),
        )

    def _is_ambiguous(self, ranked: list[RetrievedLongTermMemory]) -> bool:
        if len(ranked) < 2:
            return False

        first, second = ranked[0], ranked[1]
        same_identity = (
            first.memory.memory_key == second.memory.memory_key
            and first.memory.category == second.memory.category
        )
        if same_identity:
            return False

        return (first.score - second.score) < self.ambiguity_margin
