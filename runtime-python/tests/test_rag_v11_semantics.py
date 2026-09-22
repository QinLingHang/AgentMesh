from app.knowledge.discovery import discover_knowledge_bases
from app.schemas import KnowledgeCatalogItem
from app.semantics import KnowledgeDependency, RagPreference, analyze_task_semantics


def test_mixed_order_policy_keeps_tool_and_knowledge_and_forbids_refund():
    semantic = analyze_task_semantics(
        "查询订单 ORD-1001，再根据公司的退款政策判断能否退款，不要执行退款"
    )
    assert semantic.requires_tool is True
    assert semantic.knowledge_dependency in {
        KnowledgeDependency.OPTIONAL,
        KnowledgeDependency.REQUIRED,
    }
    assert semantic.mixed_capability_request is True
    assert "refund" in semantic.forbidden_actions


def test_explicit_rag_disable_wins_over_knowledge_keywords():
    semantic = analyze_task_semantics("我不想检索知识库，请解释 Kafka 是什么")
    assert semantic.rag_preference == RagPreference.DISABLE


def test_attachment_does_not_suppress_project_knowledge_need():
    semantic = analyze_task_semantics(
        "这份 PDF 和当前项目规范一起分析",
        has_attachments=True,
    )
    assert semantic.has_attachments is True
    assert semantic.knowledge_dependency != KnowledgeDependency.NONE


def test_explicit_authorized_knowledge_is_selected_even_with_weak_metadata():
    semantic = analyze_task_semantics("请根据资料回答")
    catalog = [
        KnowledgeCatalogItem(
            knowledgeBaseId=7,
            name="无明显关键词",
            description="",
            scope="PROJECT",
            projectId=2,
            accessible=True,
        )
    ]
    result = discover_knowledge_bases(
        "完全无关的查询词",
        semantic=semantic,
        catalog=catalog,
        explicitly_selected_ids=[7],
    )
    assert result.selected_knowledge_base_ids == [7]
    assert result.candidates[0].explicit is True


def test_metadata_is_advisory_for_required_knowledge():
    semantic = analyze_task_semantics("严格根据当前项目需求文档说明验收条件")
    catalog = [
        KnowledgeCatalogItem(
            knowledgeBaseId=11,
            name="项目资料",
            description="",
            scope="PROJECT",
            projectId=2,
            accessible=True,
        ),
        KnowledgeCatalogItem(
            knowledgeBaseId=12,
            name="其他资料",
            description="",
            scope="PROJECT",
            projectId=2,
            accessible=True,
        ),
    ]
    result = discover_knowledge_bases(
        "严格根据当前项目需求文档说明验收条件",
        semantic=semantic,
        catalog=catalog,
    )
    assert result.needed is True
    assert result.selected_knowledge_base_ids
    assert len(result.selected_knowledge_base_ids) <= 4
