"""Missing Go-authorized knowledge metadata never implicitly grants retrieval."""
import json

import pytest

from app.schemas import AgentProfile, RuntimeRequest
from app.services import RuntimeEngine, create_registry


class SpyRetriever:
    def __init__(self):
        self.calls = 0

    async def retrieve(self, query, *, top_k=5, filters=None):
        self.calls += 1
        return []


@pytest.mark.asyncio
async def test_on_without_authorized_catalog_fails_closed():
    registry = await create_registry()
    retriever = SpyRetriever()
    try:
        engine = RuntimeEngine(registry, retriever=retriever)
        # ON + REQUIRED evidence with no authorized catalog must stop before
        # Agent/Tool execution. A RuntimeError is the expected fail-closed
        # contract, not a successful RuntimeResponse with fabricated content.
        events = []
        with pytest.raises(RuntimeError, match="缺少足够的已授权证据"):
            await engine.run(RuntimeRequest(
                user_id=1, request_id="rag-no-catalog-security",
                task="根据项目知识库解释 AgentMesh 的运行机制",
                ragPolicy={"mode": "ON", "scopes": ["PROJECT"]},
                agents=[AgentProfile(
                    id=1, name="General", endpoint="internal://general", protocol="internal",
                    capabilities=["general"], provider="mock",
                )],
            ), event_sink=events.append)
        assert retriever.calls == 0
        assert any(
            event.title == "RAG Route" and json.loads(event.detail)["mode"] == "no_rag"
            for event in events
        )
        assert any(
            event.title == "Required Knowledge Pre-execution Gate"
            and event.status == "error"
            and json.loads(event.detail)["status"] == "INSUFFICIENT_EVIDENCE"
            for event in events
        )
    finally:
        await registry.stop_all()
