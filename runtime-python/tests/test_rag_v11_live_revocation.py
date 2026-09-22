"""P22/RAG V1.1: every governed retrieval must pass live authorization."""
import asyncio

import pytest

from app.knowledge.scope import KnowledgeScope, ScopedRetriever, reset_knowledge_scope, set_knowledge_scope
from app.rag.runtime import RetrievalDocument, RetrievalHit


class StubRetriever:
    def __init__(self, on_retrieve=None):
        self.calls = []
        self.on_retrieve = on_retrieve

    async def retrieve(self, query, *, top_k=5, filters=None):
        self.calls.append(dict(filters or {}))
        if self.on_retrieve:
            self.on_retrieve()
        kb = filters["knowledgeBaseId"]
        return [RetrievalHit(document=RetrievalDocument(id=f"{kb}-chunk", text="confidential"), score=0.9)]


def execute(scope, source):
    token = set_knowledge_scope(scope)
    try:
        return asyncio.run(ScopedRetriever(source).retrieve("test", filters={"userId": 8}))
    finally:
        reset_knowledge_scope(token)


def test_revoked_before_retrieval_never_queries_data():
    source = StubRetriever()
    async def auth(user, conversation, ids):
        assert (user, conversation, ids) == (8, 18, (41,))
        return ()
    result = execute(KnowledgeScope(8, 18, 2, "POLICY", (41,), auth, True), source)
    assert result == [] and source.calls == []


def test_revoked_during_retrieval_discards_response():
    source = StubRetriever()
    checks = 0
    async def auth(user, conversation, ids):
        nonlocal checks
        checks += 1
        return ids if checks == 1 else ()
    result = execute(KnowledgeScope(8, 18, 2, "POLICY", (41,), auth, True), source)
    assert result == [] and checks == 2 and len(source.calls) == 1


def test_live_authorization_never_expands_snapshot_or_candidates():
    source = StubRetriever()
    async def auth(user, conversation, ids):
        return (41, 42, 999) # malicious/broken response is not a grant
    result = execute(KnowledgeScope(8, 18, 2, "POLICY", (41,), auth, True), source)
    assert [hit.document.id for hit in result] == ["41-chunk"]
    assert source.calls == [{"userId": 8, "knowledgeBaseId": 41}]


def test_authorization_outage_fails_closed():
    source = StubRetriever()
    async def auth(user, conversation, ids):
        raise ConnectionError("Go unavailable")
    with pytest.raises(ConnectionError, match="Go unavailable"):
        execute(KnowledgeScope(8, 18, 2, "POLICY", (41,), auth, True), source)
    assert source.calls == []


def test_missing_authorizer_fails_closed():
    source = StubRetriever()
    with pytest.raises(RuntimeError, match="unavailable"):
        execute(KnowledgeScope(8, 18, 2, "POLICY", (41,), None, True), source)
    assert source.calls == []
