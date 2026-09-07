from app.rag.adaptive_router import (
    AdaptiveRAGRouter,
    RAGMode,
)


def test_business_task_routes_to_no_rag():
    router = (
        AdaptiveRAGRouter()
    )

    decision = (
        router.route(
            "Please query this order current processing status.",
            capabilities=[
                "business",
            ],
        )
    )

    assert (
        decision.mode
        == RAGMode.NO_RAG
    )

    assert (
        decision.retrieve
        is False
    )

    assert (
        decision.inject_context
        is False
    )

    assert (
        decision.top_k
        == 0
    )


def test_simple_knowledge_query_routes_to_fast_rag():
    router = (
        AdaptiveRAGRouter()
    )

    decision = (
        router.route(
            "AgentMesh 的 MCP Failure Backoff 是什么？"
        )
    )

    assert (
        decision.mode
        == RAGMode.FAST_RAG
    )

    assert (
        decision.retrieve
        is True
    )

    assert (
        decision.max_retrieval_rounds
        == 1
    )


def test_document_task_routes_to_agentic_rag():
    router = (
        AdaptiveRAGRouter()
    )

    decision = (
        router.route(
            "总结这份 PDF 文档中的关键结论",
            capabilities=[
                "document",
            ],
        )
    )

    assert (
        decision.mode
        == RAGMode.AGENTIC_RAG
    )

    assert (
        decision.retrieve
        is True
    )

    assert (
        decision.enable_query_rewrite
        is True
    )

    assert (
        decision.enable_reranker
        is True
    )


def test_comparison_routes_to_agentic_rag():
    router = (
        AdaptiveRAGRouter()
    )

    decision = (
        router.route(
            "比较 MCP、A2A 和 Tool Runtime 的区别"
        )
    )

    assert (
        decision.mode
        == RAGMode.AGENTIC_RAG
    )

    assert (
        decision.enable_multi_query
        is True
    )

    assert (
        decision.enable_decomposition
        is True
    )


def test_casual_query_routes_to_no_rag():
    router = (
        AdaptiveRAGRouter()
    )

    decision = (
        router.route(
            "你好"
        )
    )

    assert (
        decision.mode
        == RAGMode.NO_RAG
    )

    assert (
        decision.retrieve
        is False
    )