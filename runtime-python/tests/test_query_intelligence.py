from app.rag.query_intelligence import (
    QueryAnalyzer,
    QueryComplexity,
    QueryIntent,
)


def test_transactional_order_query_does_not_require_rag():
    analyzer = (
        QueryAnalyzer()
    )

    result = analyzer.analyze(
        "Please query this order current processing status.",
        capabilities=[
            "business",
        ],
    )

    assert (
        result.intent
        == QueryIntent.TRANSACTIONAL
    )

    assert (
        result.requires_external_knowledge
        is False
    )

    assert (
        result.should_rewrite
        is False
    )


def test_order_identifier_is_detected():
    analyzer = (
        QueryAnalyzer()
    )

    result = analyzer.analyze(
        "查询订单 ORDER202609030001 当前状态",
        capabilities=[
            "business",
        ],
    )

    assert (
        result.intent
        == QueryIntent.TRANSACTIONAL
    )

    assert (
        "ORDER202609030001"
        in result.detected_identifiers
    )


def test_simple_knowledge_query_requires_rag():
    analyzer = (
        QueryAnalyzer()
    )

    result = analyzer.analyze(
        "AgentMesh 的 MCP Failure Backoff 是什么？"
    )

    assert (
        result.intent
        == QueryIntent.KNOWLEDGE
    )

    assert (
        result.requires_external_knowledge
        is True
    )


def test_document_query_requires_knowledge():
    analyzer = (
        QueryAnalyzer()
    )

    result = analyzer.analyze(
        "总结这份 PDF 文档中的部署建议",
        capabilities=[
            "document",
        ],
    )

    assert (
        result.intent
        == QueryIntent.DOCUMENT
    )

    assert (
        result.requires_external_knowledge
        is True
    )


def test_comparison_query_is_high_complexity():
    analyzer = (
        QueryAnalyzer()
    )

    result = analyzer.analyze(
        "比较 AgentMesh 的 MCP、A2A 和 Tool Runtime 的区别"
    )

    assert (
        result.intent
        == QueryIntent.COMPARISON
    )

    assert (
        result.complexity
        == QueryComplexity.HIGH
    )

    assert (
        result.should_multi_query
        is True
    )

    assert (
        result.should_decompose
        is True
    )


def test_relational_query_is_high_complexity():
    analyzer = (
        QueryAnalyzer()
    )

    result = analyzer.analyze(
        "分析 Agent、Tool 和 MCP 之间的依赖关系"
    )

    assert (
        result.intent
        == QueryIntent.RELATIONAL
    )

    assert (
        result.should_decompose
        is True
    )


def test_casual_query_does_not_require_rag():
    analyzer = (
        QueryAnalyzer()
    )

    result = analyzer.analyze(
        "你好"
    )

    assert (
        result.intent
        == QueryIntent.CASUAL
    )

    assert (
        result.requires_external_knowledge
        is False
    )