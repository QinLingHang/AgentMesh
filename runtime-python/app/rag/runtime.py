from __future__ import annotations

import re

from dataclasses import (
    dataclass,
    field,
)

from typing import (
    Any,
    Protocol,
)


# =========================================================
# Retrieval Domain Models
# =========================================================


@dataclass(
    frozen=True,
    slots=True,
)
class RetrievalDocument:
    """
    Retriever 内部统一文档结构。

    后续无论来源是：

        Milvus
        pgvector
        Elasticsearch
        MySQL
        文件知识库

    最终都转换成这个结构，
    Agent Runtime 不关心底层存储。
    """

    id: str

    text: str

    source: str = ""

    metadata: dict[
        str,
        Any,
    ] = field(
        default_factory=dict
    )


@dataclass(
    frozen=True,
    slots=True,
)
class RetrievalHit:
    """
    一次检索命中的结果。

    document:
        原始文档。

    score:
        Retriever 自己计算的相关度分数。

    当前 InMemory baseline:
        0 ~ 1。

    后续 Milvus 的 vector score
    可以在 Adapter 层统一归一化。
    """

    document: RetrievalDocument

    score: float


# =========================================================
# Retriever Contract
# =========================================================


class Retriever(
    Protocol
):
    """
    AgentMesh RAG Retrieval Contract。

    Runtime 只依赖这个接口。

    它不应该知道底层到底是：

        BM25
        Vector Search
        Hybrid Search
        RRF
        Reranker
        Milvus
        Elasticsearch
    """

    async def retrieve(
        self,
        query: str,
        *,
        top_k: int = 5,
        filters: (
            dict[str, Any]
            | None
        ) = None,
    ) -> list[
        RetrievalHit
    ]:
        ...


# =========================================================
# In-Memory Baseline
# =========================================================


class InMemoryRetriever:
    """
    确定性 RAG Baseline。

    当前不是为了替代 Milvus，
    而是为了：

        1. 建立稳定 Contract；
        2. 可以跑单元测试；
        3. Agent Runtime 可以先完成接入；
        4. 后续替换存储时不修改 Agent。

    当前使用简单 lexical overlap。

    English:
        按单词分词。

    Chinese:
        按汉字拆分。

    因此中英文都能进行一个基础的
    deterministic retrieval。
    """

    def __init__(
        self,
        documents: (
            list[RetrievalDocument]
            | None
        ) = None,
    ) -> None:

        self._documents: dict[
            str,
            RetrievalDocument,
        ] = {}

        if documents:
            self.add_documents(
                documents
            )

    # =====================================================
    # Document Management
    # =====================================================

    def add_documents(
        self,
        documents: list[
            RetrievalDocument
        ],
    ) -> None:

        for document in documents:

            if not document.id:
                raise ValueError(
                    (
                        "retrieval document "
                        "id cannot be empty"
                    )
                )

            if not (
                document.text
                .strip()
            ):
                raise ValueError(
                    (
                        "retrieval document "
                        "text cannot be empty"
                    )
                )

            self._documents[
                document.id
            ] = document

    def clear(
        self,
    ) -> None:

        self._documents.clear()

    # =====================================================
    # Retrieval
    # =====================================================

    async def retrieve(
        self,
        query: str,
        *,
        top_k: int = 5,
        filters: (
            dict[str, Any]
            | None
        ) = None,
    ) -> list[
        RetrievalHit
    ]:

        query = (
            query.strip()
        )

        if not query:
            return []

        if top_k <= 0:
            return []

        query_tokens = (
            self._tokens(
                query
            )
        )

        if not query_tokens:
            return []

        hits: list[
            RetrievalHit
        ] = []

        for document in (
            self._documents
            .values()
        ):

            if not self._matches_filters(
                document,
                filters,
            ):
                continue

            document_tokens = (
                self._tokens(
                    document.text
                )
            )

            if not document_tokens:
                continue

            overlap = (
                query_tokens
                & document_tokens
            )

            if not overlap:
                continue

            # ---------------------------------------------
            # Query coverage
            #
            # 用户 Query 中有多少信息
            # 可以在 Document 中找到。
            # ---------------------------------------------

            query_coverage = (
                len(overlap)
                / max(
                    len(
                        query_tokens
                    ),
                    1,
                )
            )

            # ---------------------------------------------
            # Document precision
            #
            # Document 本身有多少部分
            # 与 Query 有关。
            # ---------------------------------------------

            document_precision = (
                len(overlap)
                / max(
                    len(
                        document_tokens
                    ),
                    1,
                )
            )

            score = (
                0.8
                * query_coverage
                + 0.2
                * document_precision
            )

            hits.append(
                RetrievalHit(
                    document=document,

                    score=round(
                        score,
                        6,
                    ),
                )
            )

        # -------------------------------------------------
        # score 高的排前面。
        #
        # id 作为 deterministic tie-break，
        # 保证测试和运行结果稳定。
        # -------------------------------------------------

        hits.sort(
            key=lambda item: (
                -item.score,
                item.document.id,
            )
        )

        return hits[
            :top_k
        ]

    # =====================================================
    # Helpers
    # =====================================================

    @staticmethod
    def _tokens(
        text: str,
    ) -> set[str]:
        """
        English:
            refund policy
            ->
            refund
            policy

        Chinese:
            退款政策
            ->
            退
            款
            政
            策

        当前是 baseline。

        后续正式 RAG：
            embedding
            BM25
            RRF
            rerank

        会替代这里。
        """

        return set(
            re.findall(
                (
                    r"[a-z0-9_]+"
                    r"|"
                    r"[\u4e00-\u9fff]"
                ),
                text.lower(),
            )
        )

    @staticmethod
    def _matches_filters(
        document: RetrievalDocument,
        filters: (
            dict[str, Any]
            | None
        ),
    ) -> bool:

        if not filters:
            return True

        for (
            key,
            expected,
        ) in filters.items():

            if (
                document
                .metadata
                .get(
                    key
                )
                != expected
            ):
                return False

        return True