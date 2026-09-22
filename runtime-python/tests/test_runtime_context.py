import json

import pytest

from app.memory import (
    InMemoryConversationMemory,
    MemoryMessage,
)

from app.rag import (
    InMemoryRetriever,
    RetrievalDocument,
)

from app.schemas import (
    AgentProfile,
    RuntimeRequest,
)

from app.services import (
    RuntimeEngine,
    create_registry,
)


def langgraph_agent() -> AgentProfile:
    return AgentProfile(
        id=700,

        name=(
            "ContextLangGraphAgent"
        ),

        description=(
            "Agent used for "
            "runtime context tests"
        ),

        endpoint=(
            "langgraph://context"
        ),

        protocol="langgraph",

        capabilities=[
            "general"
        ],

        provider="mock",
    )


@pytest.mark.asyncio
async def test_runtime_request_accepts_conversation_id_alias():
    request = (
        RuntimeRequest.model_validate(
            {
                "user_id": 1,

                "request_id":
                    "conversation-alias",

                "conversationId":
                    88,

                "task":
                    "hello",

                "agents": [
                    {
                        "id": 1,

                        "name":
                            "Agent",

                        "endpoint":
                            "internal://agent",

                        "protocol":
                            "internal",

                        "capabilities": [
                            "general"
                        ],
                    }
                ],
            }
        )
    )

    assert (
        request.conversation_id
        == 88
    )


@pytest.mark.asyncio
async def test_runtime_injects_memory_and_rag_context():
    registry = (
        await create_registry()
    )

    memory = (
        InMemoryConversationMemory()
    )

    retriever = (
        InMemoryRetriever(
            [
                RetrievalDocument(
                    id="kb-agentmesh",

                    source=(
                        "agentmesh-doc"
                    ),

                    text=(
                        "AgentMesh supports "
                        "adaptive scheduling "
                        "and dynamic DAG "
                        "collaboration."
                    ),

                    metadata={
                        "userId": 1,
                        "knowledgeBaseId": 9
                    },
                )
            ]
        )
    )

    try:
        await memory.append(
            user_id=1,

            conversation_id=99,

            message=(
                MemoryMessage(
                    role="user",

                    content=(
                        "My preferred deployment "
                        "region is East China."
                    ),
                )
            ),
        )

        engine = (
            RuntimeEngine(
                registry,

                retriever=(
                    retriever
                ),

                memory=(
                    memory
                ),
            )
        )

        result = (
            await engine.run(
                RuntimeRequest(
                    user_id=1,

                    request_id=(
                        "rag-memory-runtime"
                    ),

                    ragPolicy={"mode": "ON", "scopes": ["PROJECT"]},
                    effectiveRagPolicy={
                        "mode": "ON", "allowedScopes": ["PROJECT"],
                        "allowedKnowledgeBaseIds": [9],
                    },
                    knowledgeCatalog=[{
                        "knowledgeBaseId": 9, "name": "AgentMesh Runtime Architecture",
                        "scope": "PROJECT", "accessible": True,
                    }],

                    conversationId=99,

                    task=(
                        "What does AgentMesh "
                        "support?"
                    ),

                    agents=[
                        langgraph_agent()
                    ],
                )
            )
        )

        titles = {
            item.title
            for item
            in result.trace
        }

        assert (
            "Memory Context Loaded"
            in titles
        )

        assert (
            "RAG Retrieval Started"
            in titles
        )

        assert (
            "RAG Retrieval Completed"
            in titles
        )

        assert (
            "Agent Context Built"
            in titles
        )

        assert (
            "Memory Context Saved"
            in titles
        )

        rag_event = next(
            item
            for item
            in result.trace
            if (
                item.title
                == (
                    "RAG Retrieval "
                    "Completed"
                )
            )
        )

        rag_detail = (
            json.loads(
                rag_event.detail
            )
        )

        assert (
            rag_detail["hits"]
            == 1
        )

        context_event = next(
            item
            for item
            in result.trace
            if (
                item.title
                == "Agent Context Built"
            )
        )

        context_detail = (
            json.loads(
                context_event.detail
            )
        )

        assert (
            context_detail[
                "memory_messages"
            ]
            == 1
        )

        assert (
            context_detail[
                "rag_hits"
            ]
            == 1
        )

        assert (
            "[Current Task]"
            in result.answer
        )

        assert (
            "[Conversation Memory]"
            in result.answer
        )

        assert (
            "My preferred deployment "
            "region is East China."
            in result.answer
        )

        assert (
            "[Retrieved Knowledge]"
            in result.answer
        )

        assert (
            "AgentMesh supports "
            "adaptive scheduling"
            in result.answer
        )

    finally:
        await registry.stop_all()


@pytest.mark.asyncio
async def test_runtime_saves_completed_turn_to_memory():
    registry = (
        await create_registry()
    )

    memory = (
        InMemoryConversationMemory()
    )

    try:
        engine = (
            RuntimeEngine(
                registry,
                memory=memory,
            )
        )

        result = (
            await engine.run(
                RuntimeRequest(
                    user_id=3,

                    request_id=(
                        "memory-writeback"
                    ),

                    conversationId=123,

                    task=(
                        "Explain AgentMesh."
                    ),

                    agents=[
                        langgraph_agent()
                    ],
                )
            )
        )

        messages = (
            await memory.recent(
                user_id=3,
                conversation_id=123,
            )
        )

        assert (
            len(messages)
            == 2
        )

        assert (
            messages[0].role
            == "user"
        )

        assert (
            messages[0].content
            == "Explain AgentMesh."
        )

        assert (
            messages[1].role
            == "assistant"
        )

        assert (
            messages[1].content
            == result.answer
        )

    finally:
        await registry.stop_all()


@pytest.mark.asyncio
async def test_rag_failure_gracefully_degrades():
    class FailingRetriever:
        async def retrieve(
            self,
            query,
            *,
            top_k=5,
            filters=None,
        ):
            raise RuntimeError(
                "vector service unavailable"
            )

    registry = (
        await create_registry()
    )

    try:
        engine = (
            RuntimeEngine(
                registry,

                retriever=(
                    FailingRetriever()
                ),
            )
        )

        result = (
            await engine.run(
                RuntimeRequest(
                    user_id=1,

                    request_id=(
                        "rag-degrade"
                    ),

                    ragPolicy={"mode": "ON", "scopes": ["PROJECT"]},
                    effectiveRagPolicy={
                        "mode": "ON", "allowedScopes": ["PROJECT"],
                        "allowedKnowledgeBaseIds": [9],
                    },
                    knowledgeCatalog=[{
                        "knowledgeBaseId": 9, "name": "AgentMesh Runtime Architecture",
                        "scope": "PROJECT", "accessible": True,
                    }],

                    task=(
                        "Explain AgentMesh."
                    ),

                    agents=[
                        langgraph_agent()
                    ],
                )
            )
        )

        assert result.answer

        assert any(
            item.kind
            == "rag"

            and item.title
            == "RAG Retrieval Failed"

            and item.status
            == "error"

            for item
            in result.trace
        )

        assert any(
            item.title
            == "Agent Context Built"

            for item
            in result.trace
        )

    finally:
        await registry.stop_all()