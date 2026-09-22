"""Focused policy/discovery regression cases. Full-stack cases remain separate."""
from app.capabilities.discovery import discover_capabilities, discover_mcp_tools
from app.knowledge.discovery import discover_knowledge_bases
from app.schemas import KnowledgeCatalogItem
from app.semantics import KnowledgeDependency, RagPreference, analyze_task_semantics
from app.tools.contracts import ToolDefinition


def kb(i: int, name: str = "技术资料") -> KnowledgeCatalogItem:
    return KnowledgeCatalogItem(knowledgeBaseId=i, name=name, description="", scope="PROJECT", projectId=9)


def test_on_policy_discovers_without_keyword_cue():
    result = discover_knowledge_bases(
        "你好", semantic=analyze_task_semantics("你好"), catalog=[kb(3)], force_needed=True
    )
    assert result.needed is True
    assert result.selected_knowledge_base_ids == [3]


def test_auto_nonknowledge_skips_discovery():
    result = discover_knowledge_bases("你好", semantic=analyze_task_semantics("你好"), catalog=[kb(3)])
    assert result.needed is False
    assert result.selected_knowledge_base_ids == []


def test_unauthorized_explicit_id_not_promoted_by_python():
    result = discover_knowledge_bases(
        "严格根据资料", semantic=analyze_task_semantics("严格根据资料"),
        catalog=[kb(3)], explicitly_selected_ids=[888],
    )
    assert 888 not in result.selected_knowledge_base_ids


def test_knowledge_discovery_is_bounded():
    result = discover_knowledge_bases(
        "严格根据当前项目资料", semantic=analyze_task_semantics("严格根据当前项目资料"),
        catalog=[kb(i) for i in range(1, 25)], max_candidates=4,
    )
    assert result.needed is True
    assert len(result.selected_knowledge_base_ids) <= 4


def test_disabling_rag_in_prose_is_not_enabling_rag():
    result = analyze_task_semantics("我不想检索知识库，请解释 Kafka 是什么")
    assert result.rag_preference == RagPreference.DISABLE


def test_mcp_small_unrelated_catalog_not_exposed():
    tools = [ToolDefinition(name="sunset_alarm", description="Notify at sunset", protocol="mcp")]
    discovered = discover_mcp_tools("分析 Linux 内核栈帧", tools)
    assert discovered.selected_mcp_tool_names == []


def test_mcp_matching_metadata_is_selected():
    tools = [ToolDefinition(name="weather_lookup", description="查询当地天气温度", protocol="mcp")]
    result = discover_mcp_tools("查询当地天气温度", tools)
    assert result.selected_mcp_tool_names == ["weather_lookup"]


def test_forbidden_refund_tool_is_not_discovered_for_mixed_task():
    query = "查询订单 ORD-1001，再根据公司的退款政策判断能否退款，不要执行退款"
    semantic = analyze_task_semantics(query)
    tools = [
        ToolDefinition(name="order_lookup", description="订单查询", protocol="http"),
        ToolDefinition(name="refund_order", description="执行退款", protocol="http", riskLevel="high"),
    ]
    found = discover_capabilities(query, tools=tools, semantic_intent=semantic)
    assert semantic.knowledge_dependency != KnowledgeDependency.NONE
    assert semantic.requires_tool is True
    assert "refund_order" not in found.selected_tool_names


def test_negated_refund_is_not_selected_even_as_a_discovered_mcp_tool():
    query = "查询订单 ORD-1001 并依据退款政策解释是否符合条件，不要执行退款"
    semantic = analyze_task_semantics(query)
    tools = [
        ToolDefinition(name="refund_order", description="执行退款", protocol="mcp", riskLevel="high"),
        ToolDefinition(name="order_lookup", description="订单查询", protocol="mcp"),
    ]
    result = discover_mcp_tools(query, tools, semantic_intent=semantic)
    assert "refund_order" not in result.selected_mcp_tool_names
    assert "order_lookup" in result.selected_mcp_tool_names
