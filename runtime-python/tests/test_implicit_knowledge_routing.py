from app.semantics.analyzer import analyze_task_semantics
from app.semantics.contracts import KnowledgeDependency
from app.knowledge.discovery import discover_knowledge_bases
from app.schemas import KnowledgeCatalogItem


def test_implicit_customer_policy_needs_evidence():
    for question in (
        "你们买的东西可以七天无理由退货吗？", "这个产品保修多久？",
        "会员有什么权益？", "What is your return policy?",
    ):
        intent = analyze_task_semantics(question, enable_implicit_business=True)
        assert intent.knowledge_dependency is KnowledgeDependency.REQUIRED, question
        assert "knowledge" in intent.required_capabilities
        assert not intent.requires_tool


def test_generic_definition_is_not_company_policy():
    for question in ("什么是七天无理由退货？", "解释一下 Go slice", "What is a warranty?"):
        assert analyze_task_semantics(question, enable_implicit_business=True).knowledge_dependency is KnowledgeDependency.NONE


def test_live_order_requires_tool_not_static_policy():
    intent = analyze_task_semantics("我的订单现在到哪里了？", enable_implicit_business=True)
    assert intent.requires_tool
    assert intent.knowledge_dependency is KnowledgeDependency.NONE


def test_explicit_disable_preserves_dependency_but_does_not_grant_retrieval():
    intent = analyze_task_semantics("你们的退款政策是什么？不要检索知识库", enable_implicit_business=True)
    assert intent.knowledge_dependency is KnowledgeDependency.REQUIRED
    assert intent.rag_preference.value == "DISABLE"


def test_only_authorized_sources_can_be_discovered():
    intent = analyze_task_semantics("你们七天无理由退货吗？", enable_implicit_business=True)
    allowed = KnowledgeCatalogItem(knowledgeBaseId=1, name="售后退货政策", scope="PROJECT", accessible=True)
    forbidden = KnowledgeCatalogItem(knowledgeBaseId=2, name="退货政策", scope="PROJECT", accessible=False)
    result = discover_knowledge_bases("你们七天无理由退货吗？", semantic=intent, catalog=[allowed, forbidden])
    assert result.selected_knowledge_base_ids == [1]
    assert all(candidate.knowledge_base_id != 2 for candidate in result.candidates)
