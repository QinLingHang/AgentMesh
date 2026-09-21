from __future__ import annotations

import asyncio
import inspect
import time
from typing import Any

from pymilvus import (
    AnnSearchRequest,
    DataType,
    Function,
    FunctionType,
    MilvusClient,
    RRFRanker,
)

from app.rag.embedding import (
    EmbeddingProvider,
)

from app.rag.milvus_retriever import (
    MilvusRetriever,
)

from app.rag.reranker import (
    HeuristicReranker,
    Reranker,
)

from app.rag.runtime import (
    RetrievalDocument,
    RetrievalHit,
)


def _ann_search_request(
    *,
    data: Any,
    anns_field: str,
    param: dict[str, Any],
    limit: int,
    expression: str | None,
) -> AnnSearchRequest:
    """Build a request across the Milvus 2.6 filter/expr API transition."""

    kwargs: dict[str, Any] = {
        "data": data,
        "anns_field": anns_field,
        "param": param,
        "limit": limit,
    }
    try:
        parameters = inspect.signature(AnnSearchRequest).parameters
    except (TypeError, ValueError):
        parameters = {}
    preferred = "filter" if "filter" in parameters else "expr"
    kwargs[preferred] = expression or None
    try:
        request = AnnSearchRequest(**kwargs)
    except TypeError:
        # Keep compatibility with extension-backed or transitional clients
        # whose signature cannot be inspected reliably.
        alternate = "expr" if preferred == "filter" else "filter"
        kwargs.pop(preferred, None)
        kwargs[alternate] = expression or None
        request = AnnSearchRequest(**kwargs)

    # Keep the old attribute available to local fakes and diagnostics while
    # the real client consumes ``expr`` on the newer API.
    if preferred != "filter":
        try:
            setattr(request, "filter", expression or None)
        except Exception:
            pass
    return request


class HybridMilvusRetriever(
    MilvusRetriever
):
    """
    AgentMesh Hybrid RAG.

    Query
      │
      ├── Dense Embedding
      │       ↓
      │   Dense Search
      │
      └── Raw Query
              ↓
          BM25 Search
              ↓
         Milvus RRF
              ↓
        Model Reranker
              ↓
          Final Top-K

    Reranker failure:
        Model
          ↓ error
        Heuristic fallback
          ↓
        Runtime continues
    """

    def __init__(
        self,
        *,
        uri: str,
        collection_name: str,
        embedding: EmbeddingProvider,
        candidate_k: int = 8,
        rrf_k: int = 60,
        reranker: (
            Reranker
            | None
        ) = None,
        fallback_reranker: (
            Reranker
            | None
        ) = None,
        client: Any | None = None,
    ) -> None:

        super().__init__(
            uri=uri,
            collection_name=(
                collection_name
            ),
            embedding=embedding,
            client=client,
        )

        if candidate_k <= 0:
            raise ValueError(
                "candidate_k must be > 0"
            )

        if rrf_k <= 0:
            raise ValueError(
                "rrf_k must be > 0"
            )

        self.candidate_k = (
            candidate_k
        )

        self.rrf_k = (
            rrf_k
        )

        self.reranker = (
            reranker
            or HeuristicReranker()
        )

        self.fallback_reranker = (
            fallback_reranker
            or HeuristicReranker()
        )

    # =====================================================
    # Collection
    # =====================================================

    def _ensure_collection_sync(
        self,
    ) -> None:

        client = (
            self._get_client()
        )

        if client.has_collection(
            collection_name=(
                self.collection_name
            )
        ):
            return

        schema = (
            MilvusClient
            .create_schema(
                auto_id=False,
                enable_dynamic_field=False,
            )
        )

        schema.add_field(
            field_name="id",
            datatype=(
                DataType.VARCHAR
            ),
            is_primary=True,
            max_length=128,
        )

        # BM25 source text
        schema.add_field(
            field_name="text",
            datatype=(
                DataType.VARCHAR
            ),
            max_length=65535,
            enable_analyzer=True,
            analyzer_params={
                "type":
                    "chinese"
            },
        )

        schema.add_field(
            field_name="source",
            datatype=(
                DataType.VARCHAR
            ),
            max_length=2048,
        )

        schema.add_field(
            field_name="user_id",
            datatype=(
                DataType.INT64
            ),
        )

        schema.add_field(
            field_name="metadata",
            datatype=(
                DataType.JSON
            ),
        )

        # Dense Vector
        schema.add_field(
            field_name="vector",
            datatype=(
                DataType.FLOAT_VECTOR
            ),
            dim=(
                self.dimension
            ),
        )

        # BM25 Sparse Vector
        schema.add_field(
            field_name="sparse",
            datatype=(
                DataType
                .SPARSE_FLOAT_VECTOR
            ),
        )

        schema.add_function(
            Function(
                name=(
                    "text_bm25"
                ),

                function_type=(
                    FunctionType.BM25
                ),

                input_field_names=[
                    "text"
                ],

                output_field_names=[
                    "sparse"
                ],
            )
        )

        index_params = (
            client
            .prepare_index_params()
        )

        index_params.add_index(
            field_name="vector",
            index_type=(
                "AUTOINDEX"
            ),
            metric_type=(
                "COSINE"
            ),
        )

        index_params.add_index(
            field_name="sparse",
            index_type=(
                "SPARSE_INVERTED_INDEX"
            ),
            metric_type=(
                "BM25"
            ),
        )

        client.create_collection(
            collection_name=(
                self.collection_name
            ),
            schema=schema,
            index_params=(
                index_params
            ),
        )

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

        total_started = (
            time.perf_counter()
        )

        query = (
            query.strip()
        )

        if (
            not query
            or top_k <= 0
        ):
            return []

        await self.ensure_collection()

        candidate_k = max(
            top_k,
            self.candidate_k,
        )

        # =================================================
        # 1. Embedding
        # =================================================

        embedding_started = (
            time.perf_counter()
        )

        query_vectors = (
            await self
            .embedding
            .embed(
                [
                    query
                ]
            )
        )

        embedding_ms = int(
            (
                time.perf_counter()
                - embedding_started
            )
            * 1000
        )

        if not query_vectors:
            return []

        query_vector = (
            query_vectors[0]
        )

        milvus_filter = (
            self._build_filter(
                filters
            )
        )

        # =================================================
        # 2. Dense Request
        # =================================================

        dense_request = _ann_search_request(
            data=[query_vector],
            anns_field="vector",
            param={
                "metric_type": "COSINE",
                "params": {},
            },
            limit=candidate_k,
            expression=milvus_filter,
        )

        # =================================================
        # 3. BM25 Request
        # =================================================

        sparse_request = _ann_search_request(
            data=[query],
            anns_field="sparse",
            param={
                "metric_type": "BM25",
                "params": {},
            },
            limit=candidate_k,
            expression=milvus_filter,
        )

        client = (
            self._get_client()
        )

        # =================================================
        # 4. Milvus Hybrid Search + RRF
        # =================================================

        search_started = (
            time.perf_counter()
        )

        result = (
            await asyncio.to_thread(
                client.hybrid_search,

                collection_name=(
                    self.collection_name
                ),

                reqs=[
                    dense_request,
                    sparse_request,
                ],

                ranker=(
                    RRFRanker(
                        k=(
                            self.rrf_k
                        )
                    )
                ),

                limit=(
                    candidate_k
                ),

                output_fields=[
                    "text",
                    "source",
                    "user_id",
                    "metadata",
                ],
            )
        )

        hybrid_search_ms = int(
            (
                time.perf_counter()
                - search_started
            )
            * 1000
        )

        if not result:
            return []

        candidates: list[
            RetrievalHit
        ] = []

        for item in (
            result[0]
        ):
            entity = (
                item.get(
                    "entity",
                    {},
                )
                or {}
            )

            metadata = (
                entity.get(
                    "metadata",
                    {},
                )
                or {}
            )

            if not isinstance(
                metadata,
                dict,
            ):
                metadata = {}

            rrf_score = float(
                item.get(
                    "distance",
                    0.0,
                )
            )

            metadata = {
                **metadata,

                "retrievalMode":
                    "dense+bm25+rrf",

                "rrfScore":
                    rrf_score,
            }

            candidates.append(
                RetrievalHit(
                    document=(
                        RetrievalDocument(
                            id=str(
                                item.get(
                                    "id",
                                    "",
                                )
                            ),

                            text=str(
                                entity.get(
                                    "text",
                                    "",
                                )
                            ),

                            source=str(
                                entity.get(
                                    "source",
                                    "",
                                )
                            ),

                            metadata=(
                                metadata
                            ),
                        )
                    ),

                    score=(
                        rrf_score
                    ),
                )
            )

        # =================================================
        # 5. Model Rerank
        # =================================================

        rerank_started = (
            time.perf_counter()
        )

        rerank_fallback = False

        rerank_error = ""

        requested_reranker = str(
            getattr(
                self.reranker,
                "name",
                type(
                    self.reranker
                ).__name__,
            )
        )

        try:
            final_hits = (
                await self
                .reranker
                .rerank(
                    query,
                    candidates,
                    top_k=(
                        top_k
                    ),
                )
            )

        except Exception as exc:
            # ---------------------------------------------
            # Model Reranker 是增强能力。
            #
            # API timeout / quota / 5xx
            # 不应该直接让整个 RAG 失败。
            # ---------------------------------------------

            rerank_fallback = (
                True
            )

            rerank_error = (
                f"{type(exc).__name__}: "
                f"{exc}"
            )

            final_hits = (
                await self
                .fallback_reranker
                .rerank(
                    query,
                    candidates,
                    top_k=(
                        top_k
                    ),
                )
            )

        rerank_ms = int(
            (
                time.perf_counter()
                - rerank_started
            )
            * 1000
        )

        total_ms = int(
            (
                time.perf_counter()
                - total_started
            )
            * 1000
        )

        effective_reranker = (
            "unknown"
        )

        if final_hits:
            effective_reranker = str(
                final_hits[
                    0
                ]
                .document
                .metadata
                .get(
                    "reranker",
                    "unknown",
                )
            )

        # =================================================
        # 6. Diagnostics
        #
        # 注意：
        #
        # Milvus hybrid_search 在服务端已经完成
        # 两路召回 + RRF。
        #
        # 所以这里能够准确获得的是：
        #
        # denseLimit
        # bm25Limit
        # rrfCandidates
        #
        # 不是“两路实际返回数量”。
        # =================================================

        diagnostics = {
            "backend":
                "hybrid_milvus",

            "denseLimit":
                candidate_k,

            "bm25Limit":
                candidate_k,

            "rrfCandidates":
                len(
                    candidates
                ),

            "rerankCandidates":
                len(
                    candidates
                ),

            "finalHits":
                len(
                    final_hits
                ),

            "requestedReranker":
                requested_reranker,

            "effectiveReranker":
                effective_reranker,

            "rerankFallback":
                rerank_fallback,

            "embeddingMs":
                embedding_ms,

            "hybridSearchMs":
                hybrid_search_ms,

            "rerankMs":
                rerank_ms,

            "totalMs":
                total_ms,
        }

        if rerank_error:
            diagnostics[
                "rerankError"
            ] = (
                rerank_error[
                    :500
                ]
            )

        # =================================================
        # 7. Attach Diagnostics
        #
        # 不存 mutable shared state，
        # 因此多个并发请求不会互相覆盖指标。
        # =================================================

        output: list[
            RetrievalHit
        ] = []

        for hit in final_hits:
            metadata = {
                **hit.document.metadata,

                "ragDiagnostics":
                    diagnostics,
            }

            output.append(
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
                        hit.score
                    ),
                )
            )

        return output

    # =====================================================
    # Lifecycle
    # =====================================================

    async def aclose(
        self,
    ) -> None:

        close_reranker = (
            getattr(
                self.reranker,
                "aclose",
                None,
            )
        )

        if (
            close_reranker
            is not None
        ):
            await (
                close_reranker()
            )

        # embedding + Milvus client
        await super().aclose()
