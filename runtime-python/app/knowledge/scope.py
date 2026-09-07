from __future__ import annotations

import asyncio
import os
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any

import httpx

from app.rag.runtime import RetrievalHit


@dataclass(frozen=True, slots=True)
class KnowledgeScope:
    user_id: int
    conversation_id: int | None
    project_id: int | None
    mode: str
    knowledge_base_ids: tuple[int, ...]


_current_scope: ContextVar[KnowledgeScope | None] = ContextVar(
    "agentmesh_knowledge_scope",
    default=None,
)


def set_knowledge_scope(scope: KnowledgeScope | None) -> Token:
    return _current_scope.set(scope)


def reset_knowledge_scope(token: Token) -> None:
    _current_scope.reset(token)


class KnowledgeScopeClient:
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

    async def resolve(
        self,
        *,
        user_id: int,
        conversation_id: int | None,
    ) -> KnowledgeScope:
        params: dict[str, Any] = {
            "userId": user_id,
        }
        if conversation_id is not None:
            params["conversationId"] = conversation_id

        async with httpx.AsyncClient(
            timeout=self.timeout_seconds,
            trust_env=False,
        ) as client:
            response = await client.get(
                f"{self.base_url}/internal/v1/knowledge/scope",
                params=params,
                headers={
                    "X-Internal-Token": self.internal_token,
                },
            )
            response.raise_for_status()
            payload = response.json()

        data = payload.get("data", payload)
        ids = tuple(
            int(value)
            for value in data.get("knowledgeBaseIds", [])
            if int(value) > 0
        )

        project_id = data.get("projectId")
        return KnowledgeScope(
            user_id=int(data.get("userId", user_id)),
            conversation_id=(
                int(data["conversationId"])
                if data.get("conversationId") is not None
                else conversation_id
            ),
            project_id=(
                int(project_id)
                if project_id is not None
                else None
            ),
            mode=str(data.get("mode", "GLOBAL")),
            knowledge_base_ids=ids,
        )


class ScopedRetriever:
    """
    Request-local KnowledgeBase isolation wrapper.

    AgenticRetrievalExecutor keeps its existing security contract:
        filters = {"userId": user_id}

    This wrapper expands that trusted user filter into one exact query per
    allowed knowledgeBaseId, then merges/deduplicates the results.

    ContextVar default=None intentionally preserves direct unit/integration
    tests that instantiate RuntimeEngine outside FastAPI. Production HTTP
    execution always sets an explicit scope in app.main.
    """

    def __init__(self, inner) -> None:
        self.inner = inner

    async def retrieve(
        self,
        query: str,
        *,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievalHit]:
        scope = _current_scope.get()

        if scope is None:
            return await self.inner.retrieve(
                query,
                top_k=top_k,
                filters=filters,
            )

        base_filters = dict(filters or {})
        expected_user = base_filters.get("userId")

        if expected_user is None:
            base_filters["userId"] = scope.user_id
        elif int(expected_user) != scope.user_id:
            return []

        if not scope.knowledge_base_ids:
            return []

        groups = await asyncio.gather(
            *[
                self.inner.retrieve(
                    query,
                    top_k=top_k,
                    filters={
                        **base_filters,
                        "knowledgeBaseId": base_id,
                    },
                )
                for base_id in scope.knowledge_base_ids
            ]
        )

        best: dict[str, RetrievalHit] = {}
        for group in groups:
            for hit in group:
                key = hit.document.id
                previous = best.get(key)
                if previous is None or hit.score > previous.score:
                    best[key] = hit

        merged = list(best.values())
        merged.sort(
            key=lambda item: (
                -float(item.score),
                item.document.id,
            )
        )
        return merged[: max(0, int(top_k))]

    async def aclose(self) -> None:
        closer = getattr(self.inner, "aclose", None)
        if closer is not None:
            await closer()


def install_scoped_retriever(engine):
    original = engine.retriever
    wrapper = ScopedRetriever(original)
    engine.retriever = wrapper

    agentic = getattr(engine, "agentic_retrieval", None)
    if agentic is not None:
        agentic.retriever = wrapper

    return original, wrapper
