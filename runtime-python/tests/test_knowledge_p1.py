import pytest
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx

from app.knowledge.indexer import KnowledgeIndexInput, KnowledgeIndexer
from app.knowledge.parser import parse_document_bytes
from app.knowledge.scope import (
    KnowledgeScope,
    ScopedRetriever,
    reset_knowledge_scope,
    set_knowledge_scope,
)
from app.rag.runtime import InMemoryRetriever, RetrievalDocument, RetrievalHit


class FakeRetriever:
    def __init__(self):
        self.calls = []
        self.documents = []

    async def retrieve(self, query, *, top_k=5, filters=None):
        self.calls.append(dict(filters or {}))
        base_id = int((filters or {}).get("knowledgeBaseId", 0))
        if base_id <= 0:
            return []
        return [
            RetrievalHit(
                document=RetrievalDocument(
                    id=f"doc-{base_id}",
                    text=f"kb {base_id}",
                    source="test",
                    metadata={
                        "userId": 7,
                        "knowledgeBaseId": base_id,
                    },
                ),
                score=0.9 - base_id * 0.01,
            )
        ]

    async def upsert_documents(self, documents):
        self.documents = list(documents)
        return len(documents)


@pytest.mark.asyncio
async def test_scoped_retriever_expands_exact_knowledge_bases():
    inner = FakeRetriever()
    scoped = ScopedRetriever(inner)
    token = set_knowledge_scope(
        KnowledgeScope(
            user_id=7,
            conversation_id=10,
            project_id=3,
            mode="PROJECT",
            knowledge_base_ids=(11, 12),
        )
    )
    try:
        hits = await scoped.retrieve(
            "AgentMesh",
            top_k=5,
            filters={"userId": 7},
        )
    finally:
        reset_knowledge_scope(token)

    assert {call["knowledgeBaseId"] for call in inner.calls} == {11, 12}
    assert all(call["userId"] == 7 for call in inner.calls)
    assert {hit.document.id for hit in hits} == {"doc-11", "doc-12"}


def test_txt_parser_is_utf8_and_normalized():
    text = parse_document_bytes(
        extension="txt",
        content="AgentMesh\r\n\r\n\r\nKnowledge".encode("utf-8"),
    )
    assert text == "AgentMesh\n\nKnowledge"


@pytest.mark.asyncio
async def test_indexer_adds_tenant_and_kb_metadata():
    backend = FakeRetriever()
    indexer = KnowledgeIndexer(backend)
    count = await indexer.index(
        KnowledgeIndexInput(
            user_id=7,
            knowledge_base_id=11,
            knowledge_file_id=99,
            project_id=3,
            original_name="agentmesh.md",
            extension="md",
            checksum_sha256="abc",
        ),
        b"AgentMesh project knowledge " * 40,
    )

    assert count > 0
    assert backend.documents
    for document in backend.documents:
        assert document.metadata["userId"] == 7
        assert document.metadata["knowledgeBaseId"] == 11
        assert document.metadata["knowledgeFileId"] == 99
        assert document.metadata["projectId"] == 3
        assert "chunkIndex" in document.metadata
        assert "start" in document.metadata
        assert "end" in document.metadata


@pytest.mark.asyncio
async def test_p2_concurrent_project_and_global_retrieval_isolation():
    # Use the production deterministic retriever, not a mock which invents hits
    # from the requested scope. Every scope sees the same underlying documents.
    inner = InMemoryRetriever([
        RetrievalDocument(id=name, text="AgentMesh isolation evidence", source="fixture",
                          metadata={"userId": user, "knowledgeBaseId": base})
        for name, user, base in [("A", 7, 11), ("B", 7, 12), ("global", 7, 13), ("foreign", 8, 14)]
    ])
    scoped = ScopedRetriever(inner)

    async def retrieve(project, bases, expected):
        token = set_knowledge_scope(KnowledgeScope(7, 10, project, "PROJECT" if project else "GLOBAL", bases))
        try:
            await asyncio.sleep(0)
            hits = await scoped.retrieve("AgentMesh", filters={"userId": 7})
            assert {hit.document.id for hit in hits} == expected
            # User filters cannot widen the Go-authorized base scope.
            assert await scoped.retrieve("AgentMesh", filters={"userId": 7, "knowledgeBaseId": 14}) == []
            assert await scoped.retrieve("AgentMesh", filters={"userId": 8}) == []
        finally:
            reset_knowledge_scope(token)

    await asyncio.gather(retrieve(1, (11,), {"A"}), retrieve(2, (12,), {"B"}),
                         retrieve(None, (13,), {"global"}), retrieve(3, (), set()))
    # Explicit global scope must still work after concurrent project requests.
    await retrieve(None, (13,), {"global"})


@pytest.mark.asyncio
async def test_p2_project_index_http_does_not_write_runtime_memory(monkeypatch):
    from app import main

    backend = InMemoryRetriever([])
    memory = SimpleNamespace(append=AsyncMock(), clear=AsyncMock())
    monkeypatch.setattr(main, "knowledge_indexer", KnowledgeIndexer(backend))
    monkeypatch.setattr(main, "engine", SimpleNamespace(memory=memory))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
        response = await client.post(
            "/internal/v1/knowledge/index",
            headers={"X-Internal-Token": main.settings.internal_token},
            data={"userId": "7", "knowledgeBaseId": "11", "knowledgeFileId": "91",
                  "projectId": "1", "originalName": "p2.txt", "extension": "txt"},
            files={"file": ("p2.txt", b"AgentMesh private project evidence", "text/plain")},
        )
    assert response.status_code == 200, response.text
    assert response.json()["chunkCount"] > 0
    memory.append.assert_not_called()
    memory.clear.assert_not_called()
    token = set_knowledge_scope(KnowledgeScope(7, 10, 1, "PROJECT", (11,)))
    try:
        hits = await ScopedRetriever(backend).retrieve("AgentMesh")
        assert hits and all(hit.document.metadata["projectId"] == 1 for hit in hits)
    finally:
        reset_knowledge_scope(token)
