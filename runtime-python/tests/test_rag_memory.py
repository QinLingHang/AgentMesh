import pytest

from app.memory import (
    InMemoryConversationMemory,
    MemoryMessage,
)

from app.rag import (
    InMemoryRetriever,
    RetrievalDocument,
)


# =========================================================
# RAG
# =========================================================


@pytest.mark.asyncio
async def test_in_memory_retriever_returns_relevant_document():
    retriever = (
        InMemoryRetriever(
            [
                RetrievalDocument(
                    id="refund",

                    text=(
                        "订单退款政策："
                        "付款后七天内可以申请退款。"
                    ),

                    source="policy",
                ),

                RetrievalDocument(
                    id="shipping",

                    text=(
                        "物流通常需要"
                        "三到五个工作日。"
                    ),

                    source="policy",
                ),
            ]
        )
    )

    hits = (
        await retriever.retrieve(
            "退款政策是什么？",
            top_k=2,
        )
    )

    assert hits

    assert (
        hits[0]
        .document
        .id
        == "refund"
    )

    assert (
        hits[0].score
        > 0
    )


@pytest.mark.asyncio
async def test_in_memory_retriever_supports_metadata_filter():
    retriever = (
        InMemoryRetriever(
            [
                RetrievalDocument(
                    id="tenant-a",

                    text=(
                        "AgentMesh "
                        "deployment guide"
                    ),

                    metadata={
                        "tenantId": 1
                    },
                ),

                RetrievalDocument(
                    id="tenant-b",

                    text=(
                        "AgentMesh "
                        "deployment guide"
                    ),

                    metadata={
                        "tenantId": 2
                    },
                ),
            ]
        )
    )

    hits = (
        await retriever.retrieve(
            "AgentMesh deployment",

            filters={
                "tenantId": 2
            },
        )
    )

    assert (
        len(hits)
        == 1
    )

    assert (
        hits[0]
        .document
        .id
        == "tenant-b"
    )


@pytest.mark.asyncio
async def test_in_memory_retriever_top_k_is_bounded():
    retriever = (
        InMemoryRetriever(
            [
                RetrievalDocument(
                    id="1",
                    text="agent runtime",
                ),

                RetrievalDocument(
                    id="2",
                    text="agent runtime",
                ),

                RetrievalDocument(
                    id="3",
                    text="agent runtime",
                ),
            ]
        )
    )

    hits = (
        await retriever.retrieve(
            "agent runtime",
            top_k=2,
        )
    )

    assert (
        len(hits)
        == 2
    )


# =========================================================
# Memory
# =========================================================


@pytest.mark.asyncio
async def test_memory_preserves_conversation_order():
    memory = (
        InMemoryConversationMemory(
            max_messages=20
        )
    )

    await memory.append(
        user_id=1,
        conversation_id=100,

        message=MemoryMessage(
            role="user",
            content="hello",
        ),
    )

    await memory.append(
        user_id=1,
        conversation_id=100,

        message=MemoryMessage(
            role="assistant",
            content="hi",
        ),
    )

    messages = (
        await memory.recent(
            user_id=1,
            conversation_id=100,
        )
    )

    assert [
        item.content
        for item
        in messages
    ] == [
        "hello",
        "hi",
    ]


@pytest.mark.asyncio
async def test_memory_isolated_by_user_and_conversation():
    memory = (
        InMemoryConversationMemory()
    )

    await memory.append(
        user_id=1,
        conversation_id=10,

        message=MemoryMessage(
            role="user",
            content="user-one",
        ),
    )

    await memory.append(
        user_id=2,
        conversation_id=10,

        message=MemoryMessage(
            role="user",
            content="user-two",
        ),
    )

    first = (
        await memory.recent(
            user_id=1,
            conversation_id=10,
        )
    )

    second = (
        await memory.recent(
            user_id=2,
            conversation_id=10,
        )
    )

    assert (
        first[0].content
        == "user-one"
    )

    assert (
        second[0].content
        == "user-two"
    )


@pytest.mark.asyncio
async def test_memory_sliding_window_and_clear():
    memory = (
        InMemoryConversationMemory(
            max_messages=3
        )
    )

    for index in range(
        5
    ):
        await memory.append(
            user_id=1,
            conversation_id=1,

            message=MemoryMessage(
                role="user",

                content=(
                    f"message-{index}"
                ),
            ),
        )

    messages = (
        await memory.recent(
            user_id=1,
            conversation_id=1,
        )
    )

    assert [
        item.content
        for item
        in messages
    ] == [
        "message-2",
        "message-3",
        "message-4",
    ]

    await memory.clear(
        user_id=1,
        conversation_id=1,
    )

    assert (
        await memory.recent(
            user_id=1,
            conversation_id=1,
        )
    ) == []