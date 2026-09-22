from __future__ import annotations

import re
from collections.abc import Iterable

from .contracts import KnowledgeDependency, RagPreference, TaskSemanticIntent


_EXPLANATION = (
    "什么是", "是什么", "解释", "介绍", "区别", "差别", "原理", "为什么", "how does", "what is", "explain", "difference",
)
_ACTION = (
    "查询", "查一下", "查找", "搜索", "获取", "读取", "执行", "运行", "创建", "新建", "更新", "修改", "删除", "发送", "退款", "取消",
    "query", "lookup", "search", "fetch", "read", "execute", "run", "create", "update", "delete", "send", "refund", "cancel",
)
_KNOWLEDGE_REFERENCE = (
    "知识库", "项目资料", "项目文档", "项目规范", "项目需求", "当前项目", "本项目", "根据文档", "根据资料", "严格根据", "依据资料",
    "知识", "政策", "制度", "规范", "需求文档", "设计文档", "上传的", "我的简历", "全局知识", "global knowledge", "knowledge base",
    "project document", "project docs", "policy", "specification", "requirements document",
)
_REQUIRED_KNOWLEDGE = (
    "严格根据", "必须根据", "仅根据", "只能根据", "依据当前项目", "根据当前项目", "根据项目", "按照项目", "按照公司", "根据公司",
    "strictly based on", "only based on", "according to the project", "according to company",
)
_RAG_DISABLE = (
    "不要检索知识库", "不想检索知识库", "不要查知识库", "不检索知识库", "关闭知识库", "不用知识库", "不要使用知识库", "不使用知识库", "不要rag", "关闭rag",
    "do not use rag", "don't use rag", "do not search the knowledge base", "without rag",
)
_RAG_ENABLE = (
    "使用知识库", "检索知识库", "查询知识库", "开启知识库", "打开知识库", "启用rag", "使用rag", "查项目资料", "查全局知识",
    "use rag", "search the knowledge base", "use the knowledge base",
)
_EXTERNAL = (
    "github", "gitlab", "jira", "slack", "notion", "gmail", "outlook", "飞书", "钉钉", "企业微信", "mcp", "第三方", "外部服务", "api",
    "天气", "物流", "订单", "邮件", "邮箱", "calendar", "weather", "shipping", "order", "email",
)
_MEMORY = (
    "你记得", "还记得", "记得我", "我之前", "之前我", "我的偏好", "我的习惯", "我喜欢", "我不喜欢",
    "remember", "do you remember", "my preference", "previously I", "earlier I",
)

_TOOLISH = (
    "订单", "物流", "天气", "邮件", "数据库", "文件", "终端", "命令", "测试", "构建", "github", "gitlab", "sql", "api",
    "order", "shipping", "weather", "email", "database", "file", "terminal", "command", "test", "build",
)
_FORBID_PATTERNS = (
    ("不要执行退款", "refund"), ("不要退款", "refund"), ("不要取消订单", "cancel_order"), ("不要删除", "delete"),
    ("不要修改", "modify"), ("不要写入", "write"), ("don't refund", "refund"), ("do not refund", "refund"),
    ("don't delete", "delete"), ("do not delete", "delete"), ("do not modify", "modify"),
)


def _contains(text: str, values: Iterable[str]) -> bool:
    lower = text.casefold()
    return any(value.casefold() in lower for value in values)


def _extract_entities(text: str) -> list[str]:
    entities: list[str] = []
    for token in re.findall(r"\b[A-Z][A-Z0-9_-]{2,}\b|\b(?:ORD|PR|P)\d+[A-Z0-9_-]*\b", text):
        if token not in entities:
            entities.append(token)
    return entities[:16]


def analyze_task_semantics(
    task: str,
    *,
    has_attachments: bool = False,
    profiler_capabilities: Iterable[str] = (),
) -> TaskSemanticIntent:
    text = " ".join(str(task or "").split())
    lower = text.casefold()
    reasons: list[str] = []

    explicit_disable = _contains(text, _RAG_DISABLE)
    explicit_enable = _contains(text, _RAG_ENABLE)
    if explicit_disable:
        rag_preference = RagPreference.DISABLE
        reasons.append("user explicitly disabled knowledge retrieval")
    elif explicit_enable:
        rag_preference = RagPreference.ENABLE
        reasons.append("user explicitly requested knowledge retrieval")
    else:
        rag_preference = RagPreference.UNSPECIFIED

    knowledge_reference = _contains(text, _KNOWLEDGE_REFERENCE)
    required_knowledge = _contains(text, _REQUIRED_KNOWLEDGE)
    if explicit_disable:
        # Dependency describes the task, not the permission. A task may still
        # require evidence even when the user has disabled retrieval; the gate
        # will return DISABLED rather than silently falling back to model prior.
        dependency = KnowledgeDependency.REQUIRED if required_knowledge else (
            KnowledgeDependency.OPTIONAL if knowledge_reference else KnowledgeDependency.NONE
        )
    elif required_knowledge:
        dependency = KnowledgeDependency.REQUIRED
        reasons.append("request explicitly requires internal/project evidence")
    elif knowledge_reference or explicit_enable:
        dependency = KnowledgeDependency.OPTIONAL
        reasons.append("request references governed knowledge")
    else:
        dependency = KnowledgeDependency.NONE

    action = _contains(text, _ACTION)
    toolish = action and _contains(text, _TOOLISH)
    external = action and _contains(text, _EXTERNAL)
    requires_memory = _contains(text, _MEMORY)
    explanation = _contains(text, _EXPLANATION)
    explanation_only = explanation and not action

    forbidden: list[str] = []
    for marker, action_name in _FORBID_PATTERNS:
        if marker.casefold() in lower and action_name not in forbidden:
            forbidden.append(action_name)
            reasons.append(f"user prohibited action: {action_name}")

    capabilities = [str(item).strip() for item in profiler_capabilities if str(item).strip()]
    if dependency != KnowledgeDependency.NONE and "knowledge" not in {item.casefold() for item in capabilities}:
        capabilities.append("knowledge")
    if toolish and "tool" not in {item.casefold() for item in capabilities}:
        capabilities.append("tool")

    intents: list[str] = []
    if explanation:
        intents.append("explain")
    if toolish:
        intents.append("operate_or_observe")
    if dependency != KnowledgeDependency.NONE:
        intents.append("knowledge_grounding")
    if has_attachments:
        intents.append("attachment_analysis")
    if requires_memory:
        intents.append("memory_recall")

    mixed = toolish and dependency != KnowledgeDependency.NONE
    if mixed:
        reasons.append("request combines operational/tool work with knowledge grounding")
    if has_attachments and dependency != KnowledgeDependency.NONE:
        reasons.append("attachment and governed knowledge may be used together")

    confidence = 0.55
    if explicit_disable or explicit_enable or required_knowledge or forbidden:
        confidence = 0.96
    elif mixed or knowledge_reference or toolish:
        confidence = 0.82

    return TaskSemanticIntent(
        objective=text,
        intents=intents,
        entities=_extract_entities(text),
        requiredCapabilities=list(dict.fromkeys(capabilities)),
        forbiddenActions=forbidden,
        knowledgeDependency=dependency,
        ragPreference=rag_preference,
        requiresTool=toolish,
        requiresExternal=external,
        requiresMemory=requires_memory,
        explanationOnly=explanation_only,
        hasAttachments=has_attachments,
        mixedCapabilityRequest=mixed,
        confidence=confidence,
        reasons=reasons,
    )
