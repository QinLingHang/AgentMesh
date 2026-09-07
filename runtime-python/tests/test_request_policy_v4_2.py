from app.schemas import TaskProfile
from app.services.request_policy import (
    should_discover_mcp,
    should_retrieve_long_term_memory,
    should_use_project_rag,
)


def profile(*capabilities: str) -> TaskProfile:
    return TaskProfile(
        required_capabilities=list(capabilities or ("general",)),
        complexity="low",
        risk_level="low",
        modality=["text"],
        parallelizable=False,
    )


def test_ordinary_question_uses_base_model_instead_of_project_rag():
    assert not should_use_project_rag(
        "Python 和 Java 有什么区别？",
        profile("general"),
        has_attachments=False,
    )


def test_explicit_project_knowledge_request_keeps_rag():
    assert should_use_project_rag(
        "根据当前项目知识库总结一下登录设计。",
        profile("document"),
        has_attachments=False,
    )


def test_request_local_attachment_is_authoritative_not_project_rag():
    assert not should_use_project_rag(
        "分析这份文档的统计特征。",
        profile("document", "data"),
        has_attachments=True,
    )


def test_normal_chat_skips_mcp_discovery():
    assert not should_discover_mcp(
        "解释一下什么是标准差。",
        profile("general"),
    )


def test_explaining_mcp_does_not_open_network_discovery():
    assert not should_discover_mcp(
        "MCP 是什么？它和 Function Calling 有什么区别？",
        profile("general"),
    )


def test_explicit_tool_or_business_request_keeps_mcp():
    assert should_discover_mcp(
        "帮我查询订单状态。",
        profile("business"),
    )


def test_long_term_memory_is_retrieved_only_when_relevant():
    assert not should_retrieve_long_term_memory(
        "解释一下 Java CompletableFuture。",
        memory_overview_query=False,
    )
    assert should_retrieve_long_term_memory(
        "你记得我之前更喜欢 Go 还是 Python 吗？",
        memory_overview_query=False,
    )
    assert should_retrieve_long_term_memory(
        "随便什么",
        memory_overview_query=True,
    )
