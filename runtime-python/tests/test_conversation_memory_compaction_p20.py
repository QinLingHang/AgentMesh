from __future__ import annotations

import json

import pytest

from app.memory.conversation_context import (
    ConversationHistoryMessage,
    ConversationMemoryCapsule,
    ConversationMemoryRetriever,
    ModelBackedConversationCompactor,
    render_retrieved_conversation_memories,
)
from app.models.contracts import ModelResponse


class FakeStore:
    def __init__(self, capsules=None, window=None):
        self.capsules = list(capsules or [])
        self.window = list(window or [])
        self.upserts: list[dict] = []

    async def list_capsules(self, *, user_id, conversation_id, limit):
        return self.capsules[:limit]

    async def compaction_window(self, **kwargs):
        return list(self.window)

    async def upsert_capsule(self, *, user_id, conversation_id, payload):
        self.upserts.append(payload)
        return ConversationMemoryCapsule(
            id=99,
            user_id=user_id,
            conversation_id=conversation_id,
            start_message_id=payload["startMessageId"],
            end_message_id=payload["endMessageId"],
            summary=payload["summary"],
            facts=tuple(payload["facts"]),
            decisions=tuple(payload["decisions"]),
            open_tasks=tuple(payload["openTasks"]),
            entities=tuple(payload["entities"]),
            keywords=tuple(payload["keywords"]),
            importance=payload["importance"],
            source_hash=payload["sourceHash"],
        )


class FakeModel:
    def __init__(self):
        self.requests = []

    async def generate(self, request):
        self.requests.append(request)
        return ModelResponse(
            content=json.dumps(
                {
                    "summary": "用户要求 AgentMesh 本地 Desktop 默认内置，并继续 P20 验收。",
                    "facts": ["AgentMesh 项目目录位于 E 盘"],
                    "decisions": ["Desktop 默认 Embedded，不单独启动 9583"],
                    "open_tasks": ["继续 P20 人工验收"],
                    "entities": ["AgentMesh", "Desktop"],
                    "keywords": ["desktop", "embedded", "p20"],
                    "importance": 0.9,
                },
                ensure_ascii=False,
            ),
            provider="fake",
            model=request.model,
        )


def capsule(cid: int, end: int, summary: str, *, importance: float = 0.5):
    return ConversationMemoryCapsule(
        id=cid,
        user_id=7,
        conversation_id=123,
        start_message_id=max(1, end - 11),
        end_message_id=end,
        summary=summary,
        facts=(),
        decisions=(),
        open_tasks=(),
        entities=(),
        keywords=(),
        importance=importance,
        source_hash="a" * 64,
    )


@pytest.mark.asyncio
async def test_selective_recall_chooses_relevant_capsule_without_model_call():
    store = FakeStore(
        capsules=[
            capsule(1, 40, "Desktop 默认 Embedded，不单独启动 9583", importance=0.9),
            capsule(2, 80, "论文实验讨论多目标优化算法", importance=0.7),
            capsule(3, 120, "前端颜色和布局微调", importance=0.4),
        ]
    )
    retriever = ConversationMemoryRetriever(
        store=store,
        top_k=2,
        min_score=0.05,
        max_chars=2000,
    )

    result = await retriever.retrieve(
        user_id=7,
        conversation_id=123,
        query="Desktop 为什么还要单独启动 9583？",
    )

    assert result
    assert result[0].capsule.id == 1
    rendered = render_retrieved_conversation_memories(result)
    assert "Desktop 默认 Embedded" in rendered
    assert "论文实验" not in rendered or len(result) > 1


@pytest.mark.asyncio
async def test_compaction_calls_model_only_when_threshold_is_reached():
    messages = [
        ConversationHistoryMessage(
            id=index,
            role="user" if index % 2 else "assistant",
            content=("这是需要压缩的历史消息，包含稳定项目决策。" * 8),
        )
        for index in range(1, 13)
    ]
    store = FakeStore(window=messages)
    model = FakeModel()
    compactor = ModelBackedConversationCompactor(
        store=store,
        min_messages=12,
        max_messages=18,
        reserve_recent=8,
        min_input_chars=1000,
    )

    await compactor.compact_if_needed(
        user_id=7,
        conversation_id=123,
        model_gateway=model,
        model_name="cheap-memory-model",
    )

    assert len(model.requests) == 1
    assert model.requests[0].model == "cheap-memory-model"
    assert len(store.upserts) == 1
    assert store.upserts[0]["startMessageId"] == 1
    assert store.upserts[0]["endMessageId"] == 12
    assert len(store.upserts[0]["sourceHash"]) == 64


@pytest.mark.asyncio
async def test_short_low_value_window_waits_instead_of_paying_model_call():
    messages = [
        ConversationHistoryMessage(id=index, role="user", content="好的")
        for index in range(1, 13)
    ]
    store = FakeStore(window=messages)
    model = FakeModel()
    compactor = ModelBackedConversationCompactor(
        store=store,
        min_messages=12,
        max_messages=18,
        min_input_chars=1200,
    )

    await compactor.compact_if_needed(
        user_id=7,
        conversation_id=123,
        model_gateway=model,
        model_name="cheap-memory-model",
    )

    assert model.requests == []
    assert store.upserts == []


@pytest.mark.asyncio
async def test_compaction_redacts_secret_values_before_model_input():
    messages = [
        ConversationHistoryMessage(
            id=index,
            role="user" if index % 2 else "assistant",
            content=(
                "API_KEY=super-secret-value Bearer abcdefghijklmnop "
                "这是需要保留的项目决策。" * 5
            ),
        )
        for index in range(1, 13)
    ]
    store = FakeStore(window=messages)
    model = FakeModel()
    compactor = ModelBackedConversationCompactor(
        store=store,
        min_messages=12,
        max_messages=18,
        min_input_chars=100,
    )

    await compactor.compact_if_needed(
        user_id=7,
        conversation_id=123,
        model_gateway=model,
        model_name="cheap-memory-model",
    )

    sent = model.requests[0].messages[-1].content
    assert "super-secret-value" not in sent
    assert "abcdefghijklmnop" not in sent
    assert "[redacted]" in sent
