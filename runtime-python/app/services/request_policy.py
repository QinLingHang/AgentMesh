from __future__ import annotations

from collections.abc import Sequence

from app.schemas import TaskProfile


_PROJECT_KNOWLEDGE_SIGNALS: tuple[str, ...] = (
    "agentmesh",
    "知识库",
    "项目知识",
    "项目资料",
    "项目文档",
    "项目文件",
    "当前项目",
    "这个项目",
    "本项目",
    "从资料",
    "根据资料",
    "根据文档",
    "从文档",
    "检索",
    "retrieved knowledge",
    "knowledge base",
    "project knowledge",
    "project docs",
    "project document",
)

_ATTACHMENT_REFERENCE_SIGNALS: tuple[str, ...] = (
    "这份文档",
    "这个文档",
    "该文档",
    "这份文件",
    "这个文件",
    "上传的文件",
    "刚才的文件",
    "附件",
)

_TOOL_SIGNALS: tuple[str, ...] = (
    "调用工具",
    "使用工具",
    "执行工具",
    "调用 mcp",
    "使用 mcp",
    "查询订单",
    "订单状态",
    "物流",
    "退款",
    "支付",
    "天气",
    "发邮件",
    "发送邮件",
    "写入",
    "创建记录",
    "删除记录",
    "current time",
    "what time",
    "order status",
    "shipping",
    "refund",
    "payment",
    "weather",
    "send email",
    "use tool",
    "call tool",
)

_MEMORY_SIGNALS: tuple[str, ...] = (
    "你记得",
    "还记得",
    "记得我",
    "我之前",
    "之前我",
    "我的偏好",
    "我的习惯",
    "我喜欢",
    "我不喜欢",
    "记住",
    "忘记",
    "remember",
    "do you remember",
    "my preference",
    "my preferences",
    "forget",
)


def _contains_any(text: str, signals: Sequence[str]) -> bool:
    normalized = text.strip().lower()
    return any(signal.lower() in normalized for signal in signals)


def should_use_project_rag(
    task: str,
    profile: TaskProfile,
    *,
    has_attachments: bool,
) -> bool:
    """Return True only when Project Knowledge is actually part of the request.

    AgentMesh previously routed ordinary question-shaped prompts through Project
    RAG.  That made normal LLM questions slower and, when the project corpus had
    no matching evidence, overly conservative.  Request-local attachments are
    already authoritative evidence for their turn and must not trigger an
    unrelated Project Knowledge lookup.
    """

    if has_attachments:
        return False

    if _contains_any(task, _PROJECT_KNOWLEDGE_SIGNALS):
        return True

    # A reference such as "这份文档" without a request-local attachment most
    # likely points at material already indexed in the current project.
    if _contains_any(task, _ATTACHMENT_REFERENCE_SIGNALS):
        return True

    # A bare capability like "document" or "data" is not enough: users often
    # ask general questions such as "DOCX 怎么解析" or "标准差是什么" and expect
    # the base model to answer from its own knowledge.
    _ = profile
    return False


def should_discover_mcp(task: str, profile: TaskProfile) -> bool:
    """Avoid network MCP discovery for normal chat/document analysis turns."""

    if _contains_any(task, _TOOL_SIGNALS):
        return True

    # Business operations are the one capability family where external actions
    # are commonly intended even if the user did not literally say "tool".
    return "business" in {item.lower() for item in profile.required_capabilities}


def should_retrieve_long_term_memory(task: str, *, memory_overview_query: bool) -> bool:
    """Retrieve durable memory only when the prompt can materially benefit."""

    if memory_overview_query:
        return True
    return _contains_any(task, _MEMORY_SIGNALS)
