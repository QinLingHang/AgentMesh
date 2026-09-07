from __future__ import annotations

import pytest

from app.memory import (
    AutomaticLongTermMemoryForgetter,
    LongTermMemoryRetrievalOutcome,
    MemoryForgetDetector,
    RetrievedLongTermMemory,
    UserLongTermMemory,
)


class FakeRetriever:
    def __init__(self, memories):
        self.memories = tuple(memories)
        self.calls = []

    async def retrieve(self, *, user_id: int, query: str):
        self.calls.append((user_id, query))
        return LongTermMemoryRetrievalOutcome(
            status="completed",
            reason="memories_retrieved" if self.memories else "no_relevant_memories",
            candidate_count=len(self.memories),
            memories=self.memories,
        )


class FakeDeleteSink:
    def __init__(self):
        self.calls = []

    async def delete(self, *, user_id: int, memory_id: int):
        self.calls.append((user_id, memory_id))


def ranked(memory_id: int, key: str, content: str, score: float = 0.9):
    memory = UserLongTermMemory(
        id=memory_id,
        user_id=7,
        category="preference",
        memory_key=key,
        content=content,
        source_type="explicit_user",
        confidence=0.98,
    )
    return RetrievedLongTermMemory(
        memory=memory,
        score=score,
        semantic_score=score,
        lexical_score=score,
        relevance_score=score,
        authority_score=1.0,
    )


def test_forget_detector_requires_user_memory_semantics():
    detector = MemoryForgetDetector()
    decision = detector.detect("忘记我对 Go 代码讲解的偏好")
    assert decision.requested is True
    assert "Go" in decision.query
    assert detector.detect("忘记密码怎么办").requested is False
    assert detector.detect("别再记这个偏好").reason == "need_more_specific_request"


@pytest.mark.asyncio
async def test_explicit_forget_deletes_only_the_best_matching_memory():
    retriever = FakeRetriever([
        ranked(11, "preference.coding.explanation_style", "讲 Go 时和 Java 对比", 0.91),
        ranked(12, "preference.ui.language", "界面优先中文", 0.62),
    ])
    sink = FakeDeleteSink()
    forgetter = AutomaticLongTermMemoryForgetter(
        retriever=retriever,
        sink=sink,
    )

    outcome = await forgetter.process(
        user_id=7,
        text="忘记我对 Go 代码讲解的偏好",
    )

    assert outcome.status == "completed"
    assert outcome.reason == "memory_forgotten"
    assert sink.calls == [(7, 11)]
    assert outcome.trace_detail()["deletedCount"] == 1
    assert "content" not in str(outcome.trace_detail()).lower()


@pytest.mark.asyncio
async def test_ambiguous_forget_never_deletes():
    retriever = FakeRetriever([
        ranked(11, "preference.a", "偏好 A", 0.80),
        ranked(12, "preference.b", "偏好 B", 0.78),
    ])
    sink = FakeDeleteSink()
    forgetter = AutomaticLongTermMemoryForgetter(
        retriever=retriever,
        sink=sink,
    )

    outcome = await forgetter.process(
        user_id=7,
        text="忘记我的编码偏好",
    )

    assert outcome.reason == "ambiguous_memory_match"
    assert sink.calls == []
