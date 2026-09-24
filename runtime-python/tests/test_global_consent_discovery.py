"""Request-local Global Knowledge consent and scoped retrieval, without Milvus fakes claiming end-to-end success."""
import asyncio

from app.knowledge.discovery import discover_knowledge_bases
from app.knowledge.scope import (
    KnowledgeScope, ScopedRetriever, reset_candidate_knowledge_ids,
    reset_knowledge_scope, set_candidate_knowledge_ids, set_knowledge_scope,
)
from app.rag.runtime import RetrievalDocument, RetrievalHit
from app.schemas import KnowledgeCatalogItem
from app.semantics import analyze_task_semantics


PROMPT = "请根据我已经上传的个人资料，告诉我用户 A 的测试标记是什么？"
MARKER = "AGENTMESH_V41_GLOBAL_TEST_ONLY"


class RecordingRetriever:
    def __init__(self):
        self.calls = []

    async def retrieve(self, query, *, top_k=5, filters=None):
        self.calls.append(dict(filters or {}))
        return [RetrievalHit(
            document=RetrievalDocument(id="global-evidence", text=f"用户 A 的测试标记是 {MARKER}"),
            score=0.95,
        )]


def _discover(authorized_catalog):
    return discover_knowledge_bases(
        PROMPT,
        semantic=analyze_task_semantics(PROMPT),
        catalog=authorized_catalog,
    )


def test_uploaded_global_base_without_go_consent_cannot_be_discovered():
    result = _discover([])
    assert result.needed is True
    assert result.selected_knowledge_base_ids == []
    source = RecordingRetriever()
    scope = set_knowledge_scope(KnowledgeScope(7, 100, None, "POLICY", ()))
    try:
        assert asyncio.run(ScopedRetriever(source).retrieve(PROMPT, filters={"userId": 7})) == []
        assert source.calls == []
    finally:
        reset_knowledge_scope(scope)


def test_explicit_global_scope_allows_auto_discovery_without_forcing_kb_selection():
    catalog = [KnowledgeCatalogItem(
        knowledgeBaseId=10, name="V41 Global", description="browser acceptance fixture",
        scope="USER_GLOBAL", accessible=True,
    )]
    result = _discover(catalog)
    assert result.needed is True
    assert result.selected_knowledge_base_ids == [10]
    assert result.reason_code in {"METADATA_MATCH", "BOUNDED_FALLBACK"}
    source = RecordingRetriever()
    async def authorize(uid, conversation_id, ids):
        assert (uid, conversation_id, ids) == (7, 100, (10,))
        return (10,)
    scope = set_knowledge_scope(KnowledgeScope(
        7, 100, None, "POLICY", (10,), live_authorizer=authorize,
        require_live_authorization=True,
    ))
    candidates = set_candidate_knowledge_ids(result.selected_knowledge_base_ids)
    try:
        hits = asyncio.run(ScopedRetriever(source).retrieve(PROMPT, filters={"userId": 7}))
        assert MARKER in hits[0].document.text
        assert source.calls == [{"userId": 7, "knowledgeBaseId": 10}]
    finally:
        reset_candidate_knowledge_ids(candidates)
        reset_knowledge_scope(scope)


def test_user_b_global_opt_in_cannot_expand_to_user_a_catalog():
    result = _discover([])  # Go has filtered User A's KB out of B's catalog.
    assert result.selected_knowledge_base_ids == []
    source = RecordingRetriever()
    scope = set_knowledge_scope(KnowledgeScope(8, 200, None, "POLICY", ()))
    try:
        assert asyncio.run(ScopedRetriever(source).retrieve(PROMPT, filters={"userId": 8})) == []
        assert source.calls == []
    finally:
        reset_knowledge_scope(scope)
