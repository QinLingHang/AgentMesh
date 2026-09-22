"""Security regression: discovery cannot expand the Go-governed knowledge scope."""
import asyncio

from app.knowledge.scope import (
    KnowledgeScope,
    ScopedRetriever,
    reset_candidate_knowledge_ids,
    reset_knowledge_scope,
    set_candidate_knowledge_ids,
    set_knowledge_scope,
)
from app.rag.runtime import RetrievalDocument, RetrievalHit


class RecordingRetriever:
    def __init__(self):
        self.calls = []

    async def retrieve(self, query, *, top_k=5, filters=None):
        self.calls.append(dict(filters or {}))
        kb_id = int(filters["knowledgeBaseId"])
        return [RetrievalHit(document=RetrievalDocument(id=f"{kb_id}-chunk", text=f"kb {kb_id}"), score=0.8)]


def test_candidates_only_narrow_go_authorized_sources():
    source = RecordingRetriever()
    scoped = ScopedRetriever(source)
    scope_token = set_knowledge_scope(KnowledgeScope(6, 9, 12, "PROJECT", (101, 102)))
    candidate_token = set_candidate_knowledge_ids([102, 999])
    try:
        hits = asyncio.run(scoped.retrieve("私有资料", filters={"userId": 6}))
        assert [hit.document.id for hit in hits] == ["102-chunk"]
        assert source.calls == [{"userId": 6, "knowledgeBaseId": 102}]
    finally:
        reset_candidate_knowledge_ids(candidate_token)
        reset_knowledge_scope(scope_token)


def test_scope_rejects_cross_user_filter_and_empty_authorization():
    source = RecordingRetriever()
    scoped = ScopedRetriever(source)
    token = set_knowledge_scope(KnowledgeScope(6, 9, 12, "PROJECT", (101,)))
    try:
        assert asyncio.run(scoped.retrieve("query", filters={"userId": 7})) == []
        assert source.calls == []
    finally:
        reset_knowledge_scope(token)

    token = set_knowledge_scope(KnowledgeScope(6, 9, 12, "PROJECT", ()))
    try:
        assert asyncio.run(scoped.retrieve("query", filters={"userId": 6})) == []
        assert source.calls == []
    finally:
        reset_knowledge_scope(token)
