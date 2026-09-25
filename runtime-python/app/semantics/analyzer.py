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
# Enterprise facts can be requested without the customer knowing that a knowledge
# base exists. These are dependency cues, NEVER authorization to read a source.
# Conceptual questions ("what is a warranty") remain generic unless the user
# explicitly asks about this business's actual rules.
_BUSINESS_FACTS = (
    "本店", "这家店", "我们公司", "我们店", "我们平台", "本公司", "我们的产品", "本产品", "这个产品", "这个商品", "这款商品", "这款产品", "你们的产品", "你们的商品", "本店的", "本平台",
    "这个套餐", "这款套餐", "这个服务", "这款服务", "保修多久", "保修期", "售后政策", "退货政策", "退款政策", "退换货", "七天无理由",
    "会员权益", "会员有什么", "运费规则", "运费多少", "收费标准", "营业时间", "服务范围",
    "官方政策", "服务条款", "发货规则", "保固", "资费套餐", "服务价格",
    "your product", "your policy", "your warranty",
    "our company", "our refund policy", "your membership", "return policy", "shipping policy",
)
_BUSINESS_ENTITY = (
    "退货", "退款", "保修", "售后", "会员", "运费", "发货", "配送", "订单规则", "资费",
    "营业", "服务条款", "产品政策", "价格", "收费", "包邮", "保险", "办理", "开通", "套餐", "资格", "手续", "流程",
    "return", "refund", "warranty", "membership", "shipping", "delivery", "policy", "price", "charge",
)
_BUSINESS_OWNER = ("你们", "你家", "贵司", "贵公司", "your company", "your store", "our company")
_GENERIC_DEFINITION = (
    "什么是", "是什么意思", "概念", "原理", "科普", "一般来说", "通常来说", "一般情况下",
    "what is", "what does", "define ", "in general", "generally speaking",
)
_LIVE_PERSONAL_DATA = (
    "我的订单", "这个订单", "订单状态", "订单号", "物流到哪", "快递到哪", "我的物流",
    "我的余额", "账户余额", "账单金额", "查询订单", "订单什么时候发货", "我的包裹",
    "my order", "order status", "track my", "my balance", "my account balance",
)
_WORKFLOW_CUES = (
    "然后", "之后", "接着", "最后", "修复并", "发现问题就", "如果发现", "如果有问题",
    "分析并", "排查并", "检查并", "测试并", "先检查", "先分析", "再测试",
    "then ", "after that", "if there", "followed by", "and test", "fix and",
)
_AGENT_DELEGATION_RE = re.compile(
    r"(?:选择|使用|调用|指定|交给|让).{0,16}(?:agent|智能体)",
    re.IGNORECASE,
)


def has_implicit_business_knowledge_need(text: str) -> bool:
    """Business-specific questions need evidence even when RAG is never named."""
    lower = str(text or "").casefold()
    if _contains(lower, _GENERIC_DEFINITION) and not _contains(
        lower, ("你们", "你家", "贵司", "贵公司", "本店", "本公司", "我们公司", "我们平台", "your ", "our ")
    ):
        return False
    return _contains(lower, _BUSINESS_FACTS) or (
        _contains(lower, _BUSINESS_OWNER) and _contains(lower, _BUSINESS_ENTITY)
    )


def has_live_personal_data_need(text: str) -> bool:
    return _contains(text, _LIVE_PERSONAL_DATA)


_RAG_DISABLE = (
    "不要检索知识库", "不想检索知识库", "不要查知识库", "不检索知识库", "关闭知识库", "不用知识库", "不要使用知识库", "不使用知识库",
    "不需要知识检索", "无需知识检索", "不要知识检索", "不使用知识检索", "不需要知识库", "无需知识库",
    "不要rag", "关闭rag",
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

# Explicit capability prohibitions are deterministic policy constraints, not
# semantic guesses. They only narrow what discovery may use; they never grant
# a capability. Ambiguous capability need is still decided by semantic routing.
_FORBIDDEN_CAPABILITY_PATTERNS = {
    "mcp": (
        "不要mcp", "不要 mcp", "不需要mcp", "不需要 mcp", "无需mcp", "无需 mcp",
        "不使用mcp", "不使用 mcp", "不要使用mcp", "不要使用 mcp", "别用mcp", "别用 mcp",
        "不要调用mcp", "不要调用 mcp", "without mcp", "no mcp",
        "do not use mcp", "don't use mcp",
    ),
    "tool": (
        "不要工具", "不需要工具", "无需工具", "不要使用工具", "不使用工具", "别用工具",
        "without tools", "no tools", "do not use tools", "don't use tools",
    ),
}


def _contains(text: str, values: Iterable[str]) -> bool:
    lower = text.casefold()
    return any(value.casefold() in lower for value in values)


def _without_markers(text: str, values: Iterable[str]) -> str:
    """Remove explicit policy phrases before looking for positive intent."""
    out = text.casefold()
    for value in sorted((str(item).casefold() for item in values), key=len, reverse=True):
        out = out.replace(value, " ")
    return out


def _contains_action(text: str) -> bool:
    """Match English action verbs as tokens, never inside identifiers/terms.

    In particular ``run`` must not make the noun ``Runtime`` an operational
    request. CJK action markers intentionally keep substring semantics.
    """
    lower = text.casefold()
    for value in _ACTION:
        marker = value.casefold()
        if marker.isascii():
            pattern = rf"(?<![a-z0-9_]){re.escape(marker)}(?![a-z0-9_])"
            if re.search(pattern, lower):
                return True
        elif marker in lower:
            return True
    return False


def _extract_entities(text: str) -> list[str]:
    entities: list[str] = []
    for token in re.findall(r"\b[A-Z][A-Z0-9_-]{2,}\b|\b(?:ORD|PR|P)\d+[A-Z0-9_-]*\b", text):
        if token not in entities:
            entities.append(token)
    return entities[:16]


_INLINE_SOURCE_BOUNDARY_RE = re.compile(
    r"(?:^|[。；;]\s*)(?:文本|内容|原文|材料|source|text|content)\s*[：:]",
    re.IGNORECASE,
)


def _instruction_scope(text: str) -> str:
    """Return the instruction portion before an explicitly labelled payload.

    Content after ``文本：``/``内容：`` is user-provided data. Capability and
    policy inference must not execute or classify words that merely occur
    inside that payload (for example ``Runtime`` or ``执行计划``).
    """
    match = _INLINE_SOURCE_BOUNDARY_RE.search(text)
    if match is None:
        return text
    return text[:match.start()].strip()


def analyze_task_semantics(
    task: str,
    *,
    has_attachments: bool = False,
    profiler_capabilities: Iterable[str] = (),
    enable_implicit_business: bool = False,
) -> TaskSemanticIntent:
    text = " ".join(str(task or "").split())
    intent_text = _instruction_scope(text)
    lower = intent_text.casefold()
    reasons: list[str] = []

    explicit_disable = _contains(intent_text, _RAG_DISABLE)
    explicit_enable = _contains(intent_text, _RAG_ENABLE)
    if explicit_disable:
        rag_preference = RagPreference.DISABLE
        reasons.append("user explicitly disabled knowledge retrieval")
    elif explicit_enable:
        rag_preference = RagPreference.ENABLE
        reasons.append("user explicitly requested knowledge retrieval")
    else:
        rag_preference = RagPreference.UNSPECIFIED

    # A negated capability mention ("不需要知识检索") is a policy bound,
    # not positive evidence that governed Knowledge is needed. Remove only the
    # explicit disable phrases, then detect any independent positive reference.
    knowledge_reference = _contains(_without_markers(intent_text, _RAG_DISABLE), _KNOWLEDGE_REFERENCE)
    business_knowledge = enable_implicit_business and has_implicit_business_knowledge_need(intent_text)
    live_personal_data = enable_implicit_business and has_live_personal_data_need(intent_text)
    required_knowledge = _contains(intent_text, _REQUIRED_KNOWLEDGE) or (business_knowledge and not live_personal_data)
    if explicit_disable:
        # Dependency describes the task, not the permission. A task may still
        # require evidence even when the user has disabled retrieval; the gate
        # will return DISABLED rather than silently falling back to model prior.
        dependency = KnowledgeDependency.REQUIRED if required_knowledge else (
            KnowledgeDependency.OPTIONAL if knowledge_reference else KnowledgeDependency.NONE
        )
    elif required_knowledge:
        dependency = KnowledgeDependency.REQUIRED
        reasons.append("business_specific_evidence_required" if business_knowledge else "request explicitly requires internal/project evidence")
    elif knowledge_reference or explicit_enable:
        dependency = KnowledgeDependency.OPTIONAL
        reasons.append("request references governed knowledge")
    else:
        dependency = KnowledgeDependency.NONE

    action = _contains_action(intent_text)
    toolish = (action and _contains(intent_text, _TOOLISH)) or live_personal_data
    external = (action and _contains(intent_text, _EXTERNAL)) or live_personal_data
    requires_memory = _contains(intent_text, _MEMORY)
    explanation = _contains(intent_text, _EXPLANATION)
    explanation_only = explanation and not action

    forbidden: list[str] = []
    for marker, action_name in _FORBID_PATTERNS:
        if marker.casefold() in lower and action_name not in forbidden:
            forbidden.append(action_name)
            reasons.append(f"user prohibited action: {action_name}")

    forbidden_capabilities: list[str] = []
    for capability, markers in _FORBIDDEN_CAPABILITY_PATTERNS.items():
        if _contains(intent_text, markers):
            forbidden_capabilities.append(capability)
            reasons.append(f"user prohibited capability: {capability}")

    capabilities = [str(item).strip() for item in profiler_capabilities if str(item).strip()]
    if _AGENT_DELEGATION_RE.search(intent_text) and "agent" not in {item.casefold() for item in capabilities}:
        capabilities.append("agent")
        reasons.append("user explicitly requested Agent delegation")
    if dependency != KnowledgeDependency.NONE and "knowledge" not in {item.casefold() for item in capabilities}:
        capabilities.append("knowledge")
    if (
        toolish
        and "tool" not in {item.casefold() for item in capabilities}
        and "tool" not in forbidden_capabilities
    ):
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
    if business_knowledge:
        intents.append("business_fact_request")
    if live_personal_data:
        intents.append("live_data_request")
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
        forbiddenCapabilities=forbidden_capabilities,
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
