import json

import httpx
import pytest

from app.memory.long_term import AutomaticMemoryWriteOutcome
from app.memory.retrieval import (
    ControlPlaneLongTermMemorySource,
    HybridLongTermMemoryRetriever,
    LongTermMemoryRetrievalOutcome,
    RetrievedLongTermMemory,
    UserLongTermMemory,
    is_memory_overview_query,
)
from app.rag.runtime import RetrievalDocument, RetrievalHit
from app.schemas import AgentProfile, RuntimeContinuation, RuntimeRequest
from app.services import RuntimeEngine, create_registry
from app.services.context_builder import build_agent_context


def memory(mid, key, content, source="inferred_user", confidence=.8, user_id=7):
    return UserLongTermMemory(mid, user_id, "preference", key, content, source, confidence)


class Source:
    def __init__(self, items=None, error=None):
        self.items, self.error, self.calls = items or [], error, []

    async def list_active(self, *, user_id, limit):
        self.calls.append({"user_id": user_id, "limit": limit})
        if self.error:
            raise self.error
        return list(self.items)


class Embedding:
    def __init__(self, vectors=None, error=None):
        self.vectors, self.error = vectors, error

    async def embed(self, texts):
        if self.error:
            raise self.error
        return self.vectors if self.vectors is not None else [[1.0, 0.0] for _ in texts]


@pytest.mark.asyncio
async def test_p33_relevance_overview_limits_authority_and_global_scope():
    items = [
        memory(1, "preference.coding.explanation", "Compare Go code with Java", "manual", .7),
        memory(2, "preference.ui.color", "Always use purple dashboards", "explicit_user", 1),
        memory(3, "preference.response_language", "Respond in Chinese", "explicit_user", .9),
    ]
    source = Source(items)
    retriever = HybridLongTermMemoryRetriever(source=source, embedding=None, top_k=2, min_score=.2)
    coding = await retriever.retrieve(user_id=7, query="Explain this Go code")
    assert coding.status == "completed"
    assert coding.memories[0].memory.id == 1
    assert 2 not in [item.memory.id for item in coding.memories]
    assert len(coding.memories) <= 2
    overview = await retriever.retrieve(user_id=7, query="What do you remember about me?")
    assert overview.memories
    # A project/conversation identifier is absent from both the protocol and calls.
    for _logical_context in ("normal", "project-a", "project-b"):
        outcome = await retriever.retrieve(user_id=7, query="Explain Go code")
        assert outcome.memories[0].memory.id == 1
    assert all(call == {"user_id": 7, "limit": 100} for call in source.calls)

    authority = Source([
        memory(10, "preference.coding.manual", "Go code", "manual", .8),
        memory(11, "preference.coding.explicit", "Go code", "explicit_user", .8),
        memory(12, "preference.coding.inferred", "Go code", "inferred_user", .8),
    ])
    ranked = await HybridLongTermMemoryRetriever(
        source=authority, embedding=None, top_k=3, min_score=0,
    ).retrieve(user_id=7, query="Go code")
    assert [x.memory.source_type for x in ranked.memories] == ["manual", "explicit_user", "inferred_user"]


@pytest.mark.asyncio
async def test_p33_semantic_ranking_and_lexical_fallback():
    items = [memory(1, "preference.coding.style", "Use concise Go examples"),
             memory(2, "preference.ui.color", "Use blue")]
    semantic = await HybridLongTermMemoryRetriever(
        source=Source(items), embedding=Embedding([[1, 0], [1, 0], [0, 1]]), top_k=1, min_score=0,
    ).retrieve(user_id=7, query="software implementation")
    assert semantic.semantic_used and semantic.memories[0].memory.id == 1
    for embedding in (Embedding(error=RuntimeError("down")), Embedding([[1, 0]])):
        fallback = await HybridLongTermMemoryRetriever(
            source=Source(items), embedding=embedding, top_k=1, min_score=.1,
        ).retrieve(user_id=7, query="Explain Go code")
        assert fallback.status == "completed" and not fallback.semantic_used
        assert fallback.reason == "memories_retrieved_lexical_fallback"
        assert fallback.memories[0].memory.id == 1
    none = await HybridLongTermMemoryRetriever(
        source=Source(items), embedding=None, min_score=1,
    ).retrieve(user_id=7, query="unrelated astronomy")
    assert none.reason == "no_relevant_memories" and not none.memories


@pytest.mark.asyncio
async def test_p33_read_time_filter_and_trace_privacy():
    unsafe = [
        memory(1, "secret.password", "password: abc123", "manual"),
        memory(2, "project.database", "This project uses PostgreSQL", "manual"),
        memory(3, "knowledge.fact", "RAG evidence [1]", "manual"),
        memory(4, "tool.result", "tool secret output", "manual"),
        memory(5, "mcp.result", "MCP token output", "manual"),
        memory(6, "preference.temporary", "Today only use this format", "manual"),
        memory(7, "preference.credential", "credential: root:pw", "manual"),
        memory(8, "preference.safe", "Use concise Go examples", "explicit_user"),
    ]
    outcome = await HybridLongTermMemoryRetriever(
        source=Source(unsafe), embedding=None, min_score=0,
    ).retrieve(user_id=7, query="Explain Go")
    assert [x.memory.id for x in outcome.memories] == [8]
    assert outcome.unsafe_skipped_count == 7
    detail = json.dumps(outcome.trace_detail())
    for forbidden in ("abc123", "PostgreSQL", "RAG evidence", "root:pw", "Today only"):
        assert forbidden not in detail
    assert "memoryKey" in detail and "content" not in detail


@pytest.mark.asyncio
async def test_p33_control_plane_payload_validation():
    payload = {"data": [
        {"id": 1, "userId": 7, "category": "preference", "memoryKey": "safe.one",
         "content": "safe", "sourceType": "manual", "confidence": 2, "status": "active"},
        {"id": 2, "userId": 8, "memoryKey": "foreign", "content": "foreign", "status": "active"},
        {"id": "bad", "userId": 7, "memoryKey": "bad", "content": "bad", "status": "active"},
        {"id": 3, "userId": 7, "memoryKey": "inactive", "content": "inactive", "status": "disabled"},
        "malformed",
    ]}
    async def handler(request):
        assert request.url.path == "/internal/v1/users/7/memories"
        assert "project" not in str(request.url).lower()
        return httpx.Response(200, json=payload, request=request)
    source = ControlPlaneLongTermMemorySource(internal_token="fixture")
    original = httpx.AsyncClient
    class Client(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)
    httpx.AsyncClient = Client
    try:
        result = await source.list_active(user_id=7, limit=999)
    finally:
        httpx.AsyncClient = original
    assert len(result) == 1 and result[0].user_id == 7 and result[0].confidence == 1


def test_p33_context_sections_and_instruction_precedence():
    recalled = RetrievedLongTermMemory(memory(1, "preference.coding.style", "Always use Java", "manual"), .9, 0, .5, 1, 1)
    from app.memory.runtime import MemoryMessage
    conversation = [MemoryMessage(role="user", content="For this conversation use Python")]
    document = RetrievalDocument(id="project-a-doc", text="Project A uses Go", metadata={"source": "a.md"})
    hit = RetrievalHit(document=document, score=.9)
    context = build_agent_context(task="For this task use Rust", memory_messages=conversation,
                                  long_term_memories=[recalled], retrieval_hits=[hit])
    sections = ["[Current Task]", "[Conversation Memory]", "[User Long-term Memory]",
                "[User Memory Policy]", "[Retrieved Knowledge]", "[Citation Policy]"]
    assert all(section in context for section in sections)
    assert [context.index(section) for section in sections] == sorted(context.index(section) for section in sections)
    assert "Current Task and direct instructions" in context
    assert "Conversation Memory override stale long-term memories" in context
    assert "manual/explicit_user memories over inferred_user" in context
    assert "Never use User Long-term Memory to establish project-specific implementation facts" in context
    assert "Never cite User Long-term Memory" in context
    assert "content=Always use Java" in context and "Project A uses Go" in context


def internal_agent():
    return AgentProfile(id=1, name="General", endpoint="internal://general", protocol="internal",
                        capabilities=["general"], provider="mock")


@pytest.mark.asyncio
async def test_p33_engine_retrieval_before_write_no_self_recall_and_failure_isolation():
    order = []
    class Retriever:
        async def retrieve(self, **kwargs):
            order.append(("retrieve", kwargs))
            return LongTermMemoryRetrievalOutcome("completed", "memories_retrieved", memories=(
                RetrievedLongTermMemory(memory(1, "preference.safe", "Previously stored preference"), .9, 0, .5, 1, 1),))
    class Writer:
        async def process(self, **kwargs):
            order.append(("write", kwargs))
            return AutomaticMemoryWriteOutcome("completed", "written")
    registry = await create_registry()
    try:
        engine = RuntimeEngine(registry, long_term_memory_retriever=Retriever())
        engine.long_term_memory_writer = Writer()
        result = await engine.run(RuntimeRequest(user_id=7, request_id="p33-order",
                                  task="Remember: use Go examples", agents=[internal_agent()]))
        assert result.status == "COMPLETED"
        assert [x[0] for x in order] == ["retrieve", "write"]
        assert order[0][1] == {"user_id": 7, "query": "Remember: use Go examples"}
        trace_kinds = [item.kind for item in result.trace]
        assert trace_kinds.index("memory_retrieval") < trace_kinds.index("memory_write") < trace_kinds.index("context")
        trace = next(item for item in result.trace if item.kind == "memory_retrieval")
        assert "Previously stored preference" not in trace.detail
    finally:
        await registry.stop_all()

    for error in (httpx.HTTPStatusError("500", request=httpx.Request("GET", "http://x"), response=httpx.Response(500)),
                  httpx.ConnectError("connection", request=httpx.Request("GET", "http://x"))):
        registry = await create_registry()
        try:
            engine = RuntimeEngine(registry, long_term_memory_retriever=HybridLongTermMemoryRetriever(source=Source(error=error)))
            result = await engine.run(RuntimeRequest(user_id=7, request_id="p33-fail", task="Remember: use Go examples", agents=[internal_agent()]))
            assert result.status == "COMPLETED"
            event = next(item for item in result.trace if item.kind == "memory_retrieval")
            assert event.status == "error" and "content" not in event.detail
        finally:
            await registry.stop_all()


@pytest.mark.asyncio
async def test_p33_resume_short_circuits_retrieval():
    class Retriever:
        async def retrieve(self, **kwargs):
            raise AssertionError("retrieval invoked for continuation")
    registry = await create_registry()
    try:
        engine = RuntimeEngine(registry, long_term_memory_retriever=Retriever())
        request = RuntimeRequest(user_id=7, request_id="p33-resume", task="OTP 123456",
            continuation=RuntimeContinuation(protocol="invalid", agentId=1, capability="general",
                taskId="fixture", contextId="fixture", state="AUTH_REQUIRED"), agents=[internal_agent()])
        with pytest.raises(RuntimeError, match="unsupported runtime continuation protocol"):
            await engine.run(request)
    finally:
        await registry.stop_all()


def test_p33_memory_overview_detection_and_no_memory_context_policy():
    assert is_memory_overview_query("你还记得我对 Go 代码讲解有什么偏好吗？")
    assert is_memory_overview_query("What do you remember about me?")
    assert not is_memory_overview_query("Explain this Go function")

    document = RetrievalDocument(
        id="project-a-doc",
        text="Project A contains a plausible Go preference, but it is project evidence.",
        metadata={"source": "a.md"},
    )
    context = build_agent_context(
        task="你还记得我对 Go 代码讲解有什么偏好吗？",
        memory_messages=[],
        long_term_memories=[],
        retrieval_hits=[RetrievalHit(document=document, score=.9)],
        memory_overview_query=True,
        memory_retrieval_reason="no_active_memories",
    )
    assert "[User Long-term Memory Status]" in context
    assert "relevant_long_term_memory_found=false" in context
    assert "No relevant User Long-term Memory was found" in context
    assert "Never answer a memory-overview question from Retrieved Knowledge" in context
    assert "[Retrieved Knowledge]" not in context
    assert "Project A contains a plausible Go preference" not in context


@pytest.mark.asyncio
async def test_p33_memory_epistemic_guard_blocks_model_guess_after_forget():
    class EmptyRetriever:
        async def retrieve(self, **kwargs):
            return LongTermMemoryRetrievalOutcome(
                "completed",
                "no_active_memories",
            )

    registry = await create_registry()
    try:
        engine = RuntimeEngine(
            registry,
            long_term_memory_retriever=EmptyRetriever(),
        )
        result = await engine.run(
            RuntimeRequest(
                user_id=7,
                request_id="p33-memory-guard",
                task="你还记得我对 Go 代码讲解有什么偏好吗？",
                agents=[internal_agent()],
            )
        )
        assert result.status == "COMPLETED"
        assert "我目前没有记住" in result.answer
        assert "长期记忆" not in result.answer
        assert "和 Java 对比" not in result.answer
        assert result.citations == []

        guard = next(
            item for item in result.trace
            if item.kind == "memory_guard"
        )
        detail = json.loads(guard.detail)
        assert detail["action"] == "no_saved_memory"
        assert detail["selectedCount"] == 0
        assert detail["retrievalReason"] == "no_active_memories"
    finally:
        await registry.stop_all()
