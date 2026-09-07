from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from app.rag.query_intelligence import (
    QueryAnalysis,
    QueryAnalyzer,
    QueryComplexity,
    QueryIntent,
)


# =========================================================
# Adaptive RAG Router
#
# Query
#   ↓
# Query Intelligence
#   ↓
#
# NO_RAG
# FAST_RAG
# AGENTIC_RAG
#
# 后续：
#
# GRAPH_RAG
# MULTIMODAL_RAG
# =========================================================


class RAGMode(
    str,
    Enum,
):
    NO_RAG = "no_rag"

    FAST_RAG = "fast_rag"

    AGENTIC_RAG = (
        "agentic_rag"
    )


@dataclass(
    frozen=True,
    slots=True,
)
class RAGRouteDecision:
    mode: RAGMode

    reason: str

    confidence: float

    analysis: QueryAnalysis

    # 是否真正执行 Retriever
    retrieve: bool

    # 是否允许把 Retrieval Hit
    # 注入 Agent Context
    inject_context: bool

    # Retrieval 预算
    top_k: int

    # Agentic RAG loop 最大轮数
    max_retrieval_rounds: int

    # 后续 v2.0.2 使用
    enable_query_rewrite: bool

    enable_multi_query: bool

    enable_decomposition: bool

    enable_reranker: bool


class AdaptiveRAGRouter:
    """
    Adaptive RAG routing baseline.

    目标不是“判断一句话属于什么分类”，
    而是决定 Retrieval Strategy。

    这是 Agentic RAG 的入口控制器。
    """

    def __init__(
        self,
        analyzer: QueryAnalyzer
        | None = None,
    ) -> None:
        self._analyzer = (
            analyzer
            or QueryAnalyzer()
        )

    def route(
        self,
        query: str,
        *,
        capabilities: Sequence[
            str
        ] = (),
    ) -> RAGRouteDecision:
        analysis = (
            self._analyzer
            .analyze(
                query,
                capabilities=capabilities,
            )
        )

        # =================================================
        # NO-RAG
        #
        # Transactional / casual tasks
        #
        # 订单、支付、物流、Tool/A2A 操作，
        # 不应该先去 Milvus 搜一遍。
        # =================================================

        if (
            not analysis
            .requires_external_knowledge
        ):
            confidence = (
                0.97
                if analysis.intent
                is QueryIntent.TRANSACTIONAL
                else 0.90
            )

            return (
                RAGRouteDecision(
                    mode=RAGMode.NO_RAG,
                    reason=(
                        "query does not require "
                        "knowledge retrieval"
                    ),
                    confidence=confidence,
                    analysis=analysis,
                    retrieve=False,
                    inject_context=False,
                    top_k=0,
                    max_retrieval_rounds=0,
                    enable_query_rewrite=False,
                    enable_multi_query=False,
                    enable_decomposition=False,
                    enable_reranker=False,
                )
            )

        # =================================================
        # AGENTIC RAG
        #
        # Complex knowledge tasks:
        #
        # comparison
        # multi-hop
        # relational
        # high complexity
        #
        # 后续允许：
        #
        # rewrite
        # multi-query
        # decomposition
        # evidence grading
        # retrieval retry
        # =================================================

        agentic_intents = {
            QueryIntent.COMPARISON,
            QueryIntent.MULTI_HOP,
            QueryIntent.RELATIONAL,
        }

        if (
            analysis.intent
            in agentic_intents
            or analysis.complexity
            is QueryComplexity.HIGH
        ):
            return (
                RAGRouteDecision(
                    mode=RAGMode.AGENTIC_RAG,
                    reason=(
                        "complex knowledge task "
                        "requires adaptive retrieval"
                    ),
                    confidence=0.93,
                    analysis=analysis,
                    retrieve=True,
                    inject_context=True,
                    top_k=8,
                    max_retrieval_rounds=3,
                    enable_query_rewrite=True,
                    enable_multi_query=(
                        analysis
                        .should_multi_query
                    ),
                    enable_decomposition=(
                        analysis
                        .should_decompose
                    ),
                    enable_reranker=True,
                )
            )

        # =================================================
        # Document RAG
        #
        # 文档类任务默认也进入 Agentic，
        # 因为后续我们需要做：
        #
        # relevance grade
        # citation
        # insufficient evidence correction
        # =================================================

        if (
            analysis.intent
            is QueryIntent.DOCUMENT
        ):
            return (
                RAGRouteDecision(
                    mode=RAGMode.AGENTIC_RAG,
                    reason=(
                        "document task requires "
                        "grounded evidence retrieval"
                    ),
                    confidence=0.91,
                    analysis=analysis,
                    retrieve=True,
                    inject_context=True,
                    top_k=8,
                    max_retrieval_rounds=2,
                    enable_query_rewrite=True,
                    enable_multi_query=False,
                    enable_decomposition=False,
                    enable_reranker=True,
                )
            )

        # =================================================
        # FAST RAG
        #
        # Simple factual / knowledge query:
        #
        # 1 retrieval
        # Dense + BM25
        # RRF
        # Reranker
        #
        # 不进入昂贵 Agentic loop。
        # =================================================

        return RAGRouteDecision(
            mode=RAGMode.FAST_RAG,
            reason=(
                "simple knowledge query "
                "can use one-pass hybrid retrieval"
            ),
            confidence=0.88,
            analysis=analysis,
            retrieve=True,
            inject_context=True,
            top_k=5,
            max_retrieval_rounds=1,
            enable_query_rewrite=False,
            enable_multi_query=False,
            enable_decomposition=False,
            enable_reranker=True,
        )