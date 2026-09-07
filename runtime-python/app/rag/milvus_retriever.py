from __future__ import annotations

import asyncio

from typing import Any

from pymilvus import (
    DataType,
    MilvusClient,
)

from app.rag.embedding import (
    EmbeddingProvider,
)

from app.rag.runtime import (
    RetrievalDocument,
    RetrievalHit,
)


class MilvusRetriever:
    """
    AgentMesh Milvus Retriever.

    Responsibilities:

        RetrievalDocument
             ↓
        EmbeddingProvider
             ↓
        Milvus

    Search:

        Query
          ↓
        Embedding
          ↓
        COSINE Search
          ↓
        RetrievalHit

    Runtime 只依赖 Retriever Contract，
    并不知道这里具体使用 Milvus。
    """

    def __init__(
        self,
        *,
        uri: str,
        collection_name: str,
        embedding: EmbeddingProvider,
        client: Any | None = None,
    ) -> None:

        if not collection_name.strip():
            raise ValueError(
                (
                    "milvus collection "
                    "name cannot be empty"
                )
            )

        self.uri = (
            uri
        )

        self.collection_name = (
            collection_name
        )

        self.embedding = (
            embedding
        )

        self.dimension = (
            embedding.dimension
        )

        self._client = (
            client
        )

        self._owns_client = (
            client is None
        )

        self._collection_ready = (
            False
        )

        self._collection_lock = (
            asyncio.Lock()
        )

    # =====================================================
    # Client
    # =====================================================

    def _get_client(
        self,
    ):
        if (
            self._client
            is None
        ):
            self._client = (
                MilvusClient(
                    uri=(
                        self.uri
                    )
                )
            )

        return (
            self._client
        )

    # =====================================================
    # Collection
    # =====================================================

    async def ensure_collection(
        self,
    ) -> None:

        if self._collection_ready:
            return

        async with (
            self._collection_lock
        ):
            if self._collection_ready:
                return

            await asyncio.to_thread(
                self
                ._ensure_collection_sync
            )

            self._collection_ready = (
                True
            )

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

        # -------------------------------------------------
        # Explicit Schema
        # -------------------------------------------------

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

        schema.add_field(
            field_name="text",
            datatype=(
                DataType.VARCHAR
            ),
            max_length=65535,
        )

        schema.add_field(
            field_name="source",
            datatype=(
                DataType.VARCHAR
            ),
            max_length=2048,
        )

        # 当前 Control Plane
        # 已经有 user_id。
        #
        # 所以先以 user_id
        # 作为 RAG 数据隔离边界。
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

        schema.add_field(
            field_name="vector",
            datatype=(
                DataType.FLOAT_VECTOR
            ),
            dim=(
                self.dimension
            ),
        )

        # -------------------------------------------------
        # Vector Index
        #
        # AUTOINDEX：
        #
        # 当前 MVP 不手动绑死 IVF/HNSW 参数。
        #
        # 以后性能测试阶段再选择：
        #
        # HNSW
        # IVF_FLAT
        # AUTOINDEX
        # -------------------------------------------------

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
    # Ingestion
    # =====================================================

    async def upsert_documents(
        self,
        documents: list[
            RetrievalDocument
        ],
    ) -> int:

        if not documents:
            return 0

        await self.ensure_collection()

        vectors = (
            await self
            .embedding
            .embed(
                [
                    document.text
                    for document
                    in documents
                ]
            )
        )

        rows: list[
            dict[str, Any]
        ] = []

        for (
            document,
            vector,
        ) in zip(
            documents,
            vectors,
            strict=True,
        ):
            user_id = int(
                document
                .metadata
                .get(
                    "userId",
                    0,
                )
            )

            rows.append(
                {
                    "id":
                        document.id,

                    "text":
                        document.text,

                    "source":
                        document.source,

                    "user_id":
                        user_id,

                    "metadata":
                        document.metadata,

                    "vector":
                        vector,
                }
            )

        client = (
            self._get_client()
        )

        await asyncio.to_thread(
            client.upsert,
            collection_name=(
                self.collection_name
            ),
            data=rows,
        )

        return len(
            rows
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

        query = (
            query.strip()
        )

        if not query:
            return []

        if top_k <= 0:
            return []

        await self.ensure_collection()

        query_vectors = (
            await self
            .embedding
            .embed(
                [
                    query
                ]
            )
        )

        if not query_vectors:
            return []

        milvus_filter = (
            self._build_filter(
                filters
            )
        )

        client = (
            self._get_client()
        )

        result = (
            await asyncio.to_thread(
                client.search,

                collection_name=(
                    self
                    .collection_name
                ),

                data=[
                    query_vectors[
                        0
                    ]
                ],

                limit=(
                    top_k
                ),

                filter=(
                    milvus_filter
                ),

                output_fields=[
                    "text",
                    "source",
                    "user_id",
                    "metadata",
                ],

                search_params={
                    "metric_type":
                        "COSINE",

                    "params":
                        {},
                },
            )
        )

        if not result:
            return []

        hits: list[
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
                    {}
                )
                or {}
            )

            if not isinstance(
                metadata,
                dict,
            ):
                metadata = {}

            hits.append(
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

                    # COSINE search：
                    #
                    # Milvus 返回的 distance
                    # 在这里作为 similarity score。
                    score=float(
                        item.get(
                            "distance",
                            0.0,
                        )
                    ),
                )
            )

        return hits

    # =====================================================
    # Filters
    # =====================================================

    @staticmethod
    def _build_filter(
        filters: (
            dict[str, Any]
            | None
        ),
    ) -> str:

        if not filters:
            return ""

        expressions: list[
            str
        ] = []

        # -------------------------------------------------
        # User isolation
        # -------------------------------------------------

        if (
            "userId"
            in filters
        ):
            user_id = int(
                filters[
                    "userId"
                ]
            )

            expressions.append(
                (
                    "user_id == "
                    f"{user_id}"
                )
            )

        # -------------------------------------------------
        # Optional source filter
        # -------------------------------------------------

        if (
            "source"
            in filters
        ):
            source = str(
                filters[
                    "source"
                ]
            )

            # 防止直接把任意用户字符串
            # 拼进 Milvus filter。
            source = (
                source
                .replace(
                    "\\",
                    "\\\\",
                )
                .replace(
                    '"',
                    '\\"',
                )
            )

            expressions.append(
                (
                    'source == "'
                    f'{source}'
                    '"'
                )
            )

        return " and ".join(
            expressions
        )

    # =====================================================
    # Lifecycle
    # =====================================================

    async def aclose(
        self,
    ) -> None:

        close_embedding = (
            getattr(
                self.embedding,
                "aclose",
                None,
            )
        )

        if (
            close_embedding
            is not None
        ):
            await close_embedding()

        if (
            self._owns_client
            and self._client
            is not None
        ):
            close = getattr(
                self._client,
                "close",
                None,
            )

            if close is not None:
                await asyncio.to_thread(
                    close
                )