from __future__ import annotations

import re
from typing import Protocol

import httpx

from app.rag.runtime import (
    RetrievalDocument,
    RetrievalHit,
)


class Reranker(Protocol):
    name: str

    async def rerank(
        self,
        query: str,
        hits: list[RetrievalHit],
        *,
        top_k: int,
    ) -> list[RetrievalHit]:
        ...


# =========================================================
# Heuristic Baseline / Fallback
# =========================================================


class HeuristicReranker:
    """
    Deterministic baseline + fallback.

    RRF Score
        +
    Lexical Overlap
        ↓
    Final Score

    主要用于：
        - 单元测试
        - 无 API Key
        - Model Reranker 故障降级
    """

    name = "heuristic"

    def __init__(
        self,
        *,
        rrf_weight: float = 0.75,
        lexical_weight: float = 0.25,
    ) -> None:

        if (
            rrf_weight < 0
            or lexical_weight < 0
        ):
            raise ValueError(
                "rerank weights must be >= 0"
            )

        total = (
            rrf_weight
            + lexical_weight
        )

        if total <= 0:
            raise ValueError(
                (
                    "rerank weights "
                    "cannot both be zero"
                )
            )

        self.rrf_weight = (
            rrf_weight / total
        )

        self.lexical_weight = (
            lexical_weight / total
        )

    async def rerank(
        self,
        query: str,
        hits: list[RetrievalHit],
        *,
        top_k: int,
    ) -> list[RetrievalHit]:

        if (
            top_k <= 0
            or not hits
        ):
            return []

        query_tokens = set(
            self._tokens(query)
        )

        max_rrf_score = max(
            (
                hit.score
                for hit
                in hits
            ),
            default=0.0,
        )

        reranked: list[
            RetrievalHit
        ] = []

        for hit in hits:
            if max_rrf_score > 0:
                normalized_rrf = (
                    hit.score
                    / max_rrf_score
                )
            else:
                normalized_rrf = 0.0

            lexical_score = (
                self._lexical_score(
                    query_tokens,
                    hit.document.text,
                )
            )

            final_score = (
                self.rrf_weight
                * normalized_rrf
                +
                self.lexical_weight
                * lexical_score
            )

            metadata = {
                **hit.document.metadata,

                "reranker":
                    self.name,

                "preRerankScore":
                    float(
                        hit.score
                    ),

                "normalizedRrfScore":
                    round(
                        normalized_rrf,
                        6,
                    ),

                "lexicalScore":
                    round(
                        lexical_score,
                        6,
                    ),

                "rerankScore":
                    round(
                        final_score,
                        6,
                    ),
            }

            reranked.append(
                RetrievalHit(
                    document=(
                        RetrievalDocument(
                            id=(
                                hit.document.id
                            ),
                            text=(
                                hit.document.text
                            ),
                            source=(
                                hit.document.source
                            ),
                            metadata=(
                                metadata
                            ),
                        )
                    ),
                    score=(
                        final_score
                    ),
                )
            )

        reranked.sort(
            key=lambda item: (
                -item.score,
                item.document.id,
            )
        )

        return reranked[
            :top_k
        ]

    @classmethod
    def _lexical_score(
        cls,
        query_tokens: set[str],
        document: str,
    ) -> float:

        if not query_tokens:
            return 0.0

        document_tokens = set(
            cls._tokens(
                document
            )
        )

        if not document_tokens:
            return 0.0

        overlap = (
            query_tokens
            & document_tokens
        )

        return (
            len(overlap)
            / len(query_tokens)
        )

    @staticmethod
    def _tokens(
        text: str,
    ) -> list[str]:

        return re.findall(
            (
                r"[a-z0-9_]+"
                r"|"
                r"[\u4e00-\u9fff]"
            ),
            text.lower(),
        )


# =========================================================
# Qwen3 Model Reranker
# =========================================================


class QwenReranker:
    """
    Real semantic reranker.

    Hybrid Recall
        ↓
    RRF Candidates
        ↓
    qwen3-rerank
        ↓
    relevance_score
        ↓
    Final Top-K

    API:
        POST {base_url}/reranks
    """

    name = "qwen3-rerank"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = (
            "https://dashscope.aliyuncs.com/"
            "compatible-api/v1"
        ),
        model: str = "qwen3-rerank",
        timeout_seconds: float = 20.0,
        trust_env: bool = True,
        instruct: str = (
            "Given a web search query, "
            "retrieve relevant passages "
            "that answer the query."
        ),
        client: (
            httpx.AsyncClient
            | None
        ) = None,
    ) -> None:

        api_key = (
            api_key.strip()
        )

        if not api_key:
            raise ValueError(
                (
                    "reranker api key "
                    "is required"
                )
            )

        # 防止再次出现之前中文占位 Key
        # 导致 HTTP Header 编码错误。
        if not api_key.isascii():
            raise ValueError(
                (
                    "reranker api key "
                    "must contain ASCII "
                    "characters only"
                )
            )

        self.api_key = (
            api_key
        )

        self.base_url = (
            base_url
            .rstrip("/")
        )

        self.model = (
            model
        )

        self.instruct = (
            instruct
        )

        self._owns_client = (
            client is None
        )

        self._client = (
            client
            if client is not None
            else httpx.AsyncClient(
                timeout=(
                    timeout_seconds
                ),
                trust_env=(
                    trust_env
                ),
            )
        )

    async def rerank(
        self,
        query: str,
        hits: list[RetrievalHit],
        *,
        top_k: int,
    ) -> list[RetrievalHit]:

        query = (
            query.strip()
        )

        if (
            not query
            or not hits
            or top_k <= 0
        ):
            return []

        documents = [
            hit.document.text
            for hit
            in hits
        ]

        payload = {
            "model":
                self.model,

            "query":
                query,

            "documents":
                documents,

            "top_n":
                min(
                    top_k,
                    len(hits),
                ),

            "instruct":
                self.instruct,
        }

        response = (
            await self
            ._client
            .post(
                (
                    f"{self.base_url}"
                    "/reranks"
                ),
                headers={
                    "Authorization":
                        (
                            "Bearer "
                            f"{self.api_key}"
                        ),

                    "Content-Type":
                        "application/json",
                },
                json=payload,
            )
        )

        response.raise_for_status()

        body = (
            response.json()
        )

        # qwen3-rerank:
        #   results 在顶层。
        #
        # 同时兼容部分旧式 DashScope：
        #   output.results
        results = (
            body.get(
                "results"
            )
        )

        if results is None:
            output = (
                body.get(
                    "output",
                    {},
                )
                or {}
            )

            results = (
                output.get(
                    "results"
                )
            )

        if not isinstance(
            results,
            list,
        ):
            raise RuntimeError(
                (
                    "invalid reranker "
                    "response: results "
                    "not found"
                )
            )

        reranked: list[
            RetrievalHit
        ] = []

        used_indexes: set[
            int
        ] = set()

        for item in results:
            index = int(
                item[
                    "index"
                ]
            )

            if (
                index < 0
                or index >= len(hits)
            ):
                continue

            if index in used_indexes:
                continue

            used_indexes.add(
                index
            )

            relevance_score = float(
                item.get(
                    "relevance_score",
                    0.0,
                )
            )

            original = (
                hits[index]
            )

            metadata = {
                **original
                .document
                .metadata,

                "reranker":
                    self.model,

                "preRerankScore":
                    float(
                        original.score
                    ),

                "modelRerankScore":
                    relevance_score,
            }

            reranked.append(
                RetrievalHit(
                    document=(
                        RetrievalDocument(
                            id=(
                                original
                                .document
                                .id
                            ),

                            text=(
                                original
                                .document
                                .text
                            ),

                            source=(
                                original
                                .document
                                .source
                            ),

                            metadata=(
                                metadata
                            ),
                        )
                    ),

                    score=(
                        relevance_score
                    ),
                )
            )

        if not reranked:
            raise RuntimeError(
                (
                    "reranker returned "
                    "no valid results"
                )
            )

        return reranked[
            :top_k
        ]

    async def aclose(
        self,
    ) -> None:

        if not self._owns_client:
            return

        await (
            self
            ._client
            .aclose()
        )