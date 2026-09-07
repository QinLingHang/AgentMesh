from __future__ import annotations

import re

from dataclasses import dataclass
from enum import Enum
from typing import Sequence


# =========================================================
# Query Intelligence
#
# User Query
#     ↓
# QueryAnalyzer
#     ↓
# Intent / Complexity / Knowledge Need
#
# 这一层只负责“理解问题”，
# 不负责真正执行 Retrieval。
#
# 后续 v2.0.2 会增加：
#
# Model-backed Query Analyzer
# Query Rewrite
# Multi Query
# Query Decomposition
# =========================================================


class QueryIntent(
    str,
    Enum,
):
    CASUAL = "casual"

    TRANSACTIONAL = "transactional"

    KNOWLEDGE = "knowledge"

    DOCUMENT = "document"

    COMPARISON = "comparison"

    MULTI_HOP = "multi_hop"

    RELATIONAL = "relational"


class QueryComplexity(
    str,
    Enum,
):
    LOW = "low"

    MEDIUM = "medium"

    HIGH = "high"


@dataclass(
    frozen=True,
    slots=True,
)
class QueryAnalysis:
    original_query: str

    normalized_query: str

    intent: QueryIntent

    complexity: QueryComplexity

    requires_external_knowledge: bool

    should_rewrite: bool

    should_multi_query: bool

    should_decompose: bool

    detected_identifiers: tuple[
        str,
        ...,
    ] = ()

    matched_signals: tuple[
        str,
        ...,
    ] = ()


# =========================================================
# Strong Transaction Signals
#
# 这类任务通常应该：
#
# Tool / MCP / A2A
#
# 而不是：
#
# Milvus RAG
# =========================================================


_TRANSACTION_TERMS = {
    "order",
    "订单",
    "物流",
    "logistics",
    "shipping",
    "退款",
    "refund",
    "支付",
    "payment",
    "余额",
    "balance",
    "账户",
    "account",
    "查询状态",
    "current status",
    "processing status",
    "track",
    "tracking",
}


# =========================================================
# Document / Knowledge Signals
# =========================================================


_DOCUMENT_TERMS = {
    "document",
    "documents",
    "pdf",
    "paper",
    "article",
    "report",
    "manual",
    "knowledge base",
    "knowledge",
    "文档",
    "文件",
    "论文",
    "报告",
    "手册",
    "知识库",
    "材料",
}


_KNOWLEDGE_TERMS = {
    "是什么",
    "什么意思",
    "解释",
    "介绍",
    "原理",
    "机制",
    "为什么",
    "如何实现",
    "怎么实现",
    "what is",
    "what does",
    "explain",
    "why",
    "how does",
    "architecture",
    "design",
    "机制",
    "架构",
    "设计",
    "原理",
    "部署",
    "配置",
    "规范",
    "策略",
}


_COMPARISON_TERMS = {
    "比较",
    "对比",
    "区别",
    "差异",
    "优缺点",
    "相比",
    "versus",
    " vs ",
    "difference",
    "compare",
    "comparison",
}


_RELATIONAL_TERMS = {
    "关系",
    "关联",
    "依赖",
    "影响",
    "因果",
    "联系",
    "relationship",
    "related",
    "dependency",
    "dependencies",
    "connection",
}


_MULTI_HOP_TERMS = {
    "综合",
    "结合",
    "分别分析",
    "多方面",
    "同时考虑",
    "根据以上",
    "基于多个",
    "cross document",
    "across documents",
    "multi hop",
    "multi-hop",
}


_CASUAL_TERMS = {
    "你好",
    "您好",
    "hello",
    "hi",
    "hey",
    "谢谢",
    "thanks",
    "thank you",
}


# =========================================================
# Identifier
#
# 例如：
#
# ORDER202609030001
# ORD-1001
# HTTP 502
#
# 业务标识符出现时，通常更偏向实时业务系统，
# 而不是静态知识库。
# =========================================================


_IDENTIFIER_PATTERNS = (
    re.compile(
        r"\bORDER[A-Z0-9_-]*\d+[A-Z0-9_-]*\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bORD[-_]?[A-Z0-9]+\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:HTTP\s*)?[1-5]\d{2}\b",
        re.IGNORECASE,
    ),
)


def _normalize(
    text: str,
) -> str:
    return " ".join(
        text
        .strip()
        .split()
    )


def _contains_any(
    text: str,
    terms: set[str],
) -> list[str]:
    lowered = (
        text.lower()
    )

    return [
        term
        for term in terms
        if term.lower()
        in lowered
    ]


def _detect_identifiers(
    text: str,
) -> tuple[
    str,
    ...,
]:
    found: list[str] = []

    for pattern in (
        _IDENTIFIER_PATTERNS
    ):
        for match in (
            pattern.findall(
                text,
            )
        ):
            value = str(
                match
            ).strip()

            if (
                value and
                value not in found
            ):
                found.append(
                    value
                )

    return tuple(
        found
    )


class QueryAnalyzer:
    """
    Deterministic Query Intelligence baseline.

    为什么第一版不用 LLM？

    1. Router 必须有可重复测试的 deterministic baseline。
    2. Model Router 后续可以作为第二层覆盖。
    3. 如果模型异常，仍然能够 fallback 到这里。
    4. 后续 RAG Eval 可以比较：
       heuristic vs model-backed router。
    """

    def analyze(
        self,
        query: str,
        *,
        capabilities: Sequence[
            str
        ] = (),
    ) -> QueryAnalysis:
        original = (
            query or ""
        )

        normalized = (
            _normalize(
                original
            )
        )

        if not normalized:
            return QueryAnalysis(
                original_query=original,
                normalized_query="",
                intent=QueryIntent.CASUAL,
                complexity=QueryComplexity.LOW,
                requires_external_knowledge=False,
                should_rewrite=False,
                should_multi_query=False,
                should_decompose=False,
            )

        lowered = (
            normalized.lower()
        )

        capability_set = {
            value
            .strip()
            .lower()
            for value in capabilities
            if value.strip()
        }

        identifiers = (
            _detect_identifiers(
                normalized
            )
        )

        transaction_signals = (
            _contains_any(
                normalized,
                _TRANSACTION_TERMS,
            )
        )

        document_signals = (
            _contains_any(
                normalized,
                _DOCUMENT_TERMS,
            )
        )

        knowledge_signals = (
            _contains_any(
                normalized,
                _KNOWLEDGE_TERMS,
            )
        )

        comparison_signals = (
            _contains_any(
                normalized,
                _COMPARISON_TERMS,
            )
        )

        relational_signals = (
            _contains_any(
                normalized,
                _RELATIONAL_TERMS,
            )
        )

        multi_hop_signals = (
            _contains_any(
                normalized,
                _MULTI_HOP_TERMS,
            )
        )

        casual_signals = (
            _contains_any(
                normalized,
                _CASUAL_TERMS,
            )
        )

        matched: list[str] = []

        # =================================================
        # Capability-driven signals
        # =================================================

        document_capabilities = {
            "document",
            "retrieval",
            "rag",
            "research",
            "knowledge",
            "summarization",
        }

        transactional_capabilities = {
            "business",
            "order",
            "logistics",
            "transaction",
            "payment",
        }

        if (
            capability_set &
            document_capabilities
        ):
            matched.append(
                "knowledge_capability"
            )

        if (
            capability_set &
            transactional_capabilities
        ):
            matched.append(
                "transactional_capability"
            )

        # =================================================
        # Strong transactional route
        # =================================================

        if (
            transaction_signals and
            (
                identifiers or
                capability_set &
                transactional_capabilities
            )
        ):
            matched.extend(
                transaction_signals
            )

            return QueryAnalysis(
                original_query=original,
                normalized_query=normalized,
                intent=QueryIntent.TRANSACTIONAL,
                complexity=QueryComplexity.LOW,
                requires_external_knowledge=False,
                should_rewrite=False,
                should_multi_query=False,
                should_decompose=False,
                detected_identifiers=identifiers,
                matched_signals=tuple(
                    matched
                ),
            )

        # =================================================
        # Comparison
        # =================================================

        if comparison_signals:
            matched.extend(
                comparison_signals
            )

            return QueryAnalysis(
                original_query=original,
                normalized_query=normalized,
                intent=QueryIntent.COMPARISON,
                complexity=QueryComplexity.HIGH,
                requires_external_knowledge=True,
                should_rewrite=True,
                should_multi_query=True,
                should_decompose=True,
                detected_identifiers=identifiers,
                matched_signals=tuple(
                    matched
                ),
            )

        # =================================================
        # Relational / future GraphRAG candidate
        # =================================================

        if relational_signals:
            matched.extend(
                relational_signals
            )

            return QueryAnalysis(
                original_query=original,
                normalized_query=normalized,
                intent=QueryIntent.RELATIONAL,
                complexity=QueryComplexity.HIGH,
                requires_external_knowledge=True,
                should_rewrite=True,
                should_multi_query=True,
                should_decompose=True,
                detected_identifiers=identifiers,
                matched_signals=tuple(
                    matched
                ),
            )

        # =================================================
        # Multi-hop
        # =================================================

        if multi_hop_signals:
            matched.extend(
                multi_hop_signals
            )

            return QueryAnalysis(
                original_query=original,
                normalized_query=normalized,
                intent=QueryIntent.MULTI_HOP,
                complexity=QueryComplexity.HIGH,
                requires_external_knowledge=True,
                should_rewrite=True,
                should_multi_query=True,
                should_decompose=True,
                detected_identifiers=identifiers,
                matched_signals=tuple(
                    matched
                ),
            )

        # =================================================
        # Document analysis
        # =================================================

        if (
            document_signals or
            capability_set &
            document_capabilities
        ):
            matched.extend(
                document_signals
            )

            return QueryAnalysis(
                original_query=original,
                normalized_query=normalized,
                intent=QueryIntent.DOCUMENT,
                complexity=QueryComplexity.MEDIUM,
                requires_external_knowledge=True,
                should_rewrite=True,
                should_multi_query=False,
                should_decompose=False,
                detected_identifiers=identifiers,
                matched_signals=tuple(
                    matched
                ),
            )

        # =================================================
        # Knowledge question
        # =================================================

        if knowledge_signals:
            matched.extend(
                knowledge_signals
            )

            return QueryAnalysis(
                original_query=original,
                normalized_query=normalized,
                intent=QueryIntent.KNOWLEDGE,
                complexity=QueryComplexity.MEDIUM,
                requires_external_knowledge=True,
                should_rewrite=True,
                should_multi_query=False,
                should_decompose=False,
                detected_identifiers=identifiers,
                matched_signals=tuple(
                    matched
                ),
            )

        # =================================================
        # Transaction without explicit ID
        #
        # 例如：
        #
        # Please query this order status
        #
        # 当前 Task Profiler 已经可能给出 business，
        # 因此仍然优先 NO-RAG。
        # =================================================

        if (
            transaction_signals or
            capability_set &
            transactional_capabilities
        ):
            matched.extend(
                transaction_signals
            )

            return QueryAnalysis(
                original_query=original,
                normalized_query=normalized,
                intent=QueryIntent.TRANSACTIONAL,
                complexity=QueryComplexity.LOW,
                requires_external_knowledge=False,
                should_rewrite=False,
                should_multi_query=False,
                should_decompose=False,
                detected_identifiers=identifiers,
                matched_signals=tuple(
                    matched
                ),
            )

        # =================================================
        # Casual
        # =================================================

        if (
            casual_signals and
            len(
                normalized
            ) <= 40
        ):
            matched.extend(
                casual_signals
            )

            return QueryAnalysis(
                original_query=original,
                normalized_query=normalized,
                intent=QueryIntent.CASUAL,
                complexity=QueryComplexity.LOW,
                requires_external_knowledge=False,
                should_rewrite=False,
                should_multi_query=False,
                should_decompose=False,
                detected_identifiers=identifiers,
                matched_signals=tuple(
                    matched
                ),
            )

        # =================================================
        # Question-like fallback
        #
        # 对明显问题型 Query：
        #
        # ? / ？ / how / why / what
        #
        # 给 FAST_RAG 一个机会。
        # =================================================

        question_like = (
            normalized.endswith(
                ("?", "？")
            )
            or lowered.startswith(
                (
                    "what ",
                    "why ",
                    "how ",
                    "where ",
                    "when ",
                    "which ",
                )
            )
        )

        if question_like:
            return QueryAnalysis(
                original_query=original,
                normalized_query=normalized,
                intent=QueryIntent.KNOWLEDGE,
                complexity=QueryComplexity.MEDIUM,
                requires_external_knowledge=True,
                should_rewrite=True,
                should_multi_query=False,
                should_decompose=False,
                detected_identifiers=identifiers,
                matched_signals=(
                    "question_like",
                ),
            )

        # =================================================
        # Conservative fallback
        #
        # 不再像旧 Runtime 那样：
        #
        # 所有任务都无脑 RAG。
        #
        # 默认不检索。
        # =================================================

        return QueryAnalysis(
            original_query=original,
            normalized_query=normalized,
            intent=QueryIntent.CASUAL,
            complexity=QueryComplexity.LOW,
            requires_external_knowledge=False,
            should_rewrite=False,
            should_multi_query=False,
            should_decompose=False,
            detected_identifiers=identifiers,
            matched_signals=(),
        )