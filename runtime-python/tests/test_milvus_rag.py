import math

import pytest

from app.knowledge.indexer import KnowledgeIndexer
from app.rag import (
    HashEmbeddingProvider,
    MilvusRetriever,
    RetrievalDocument,
    chunk_text,
)


# =========================================================
# Hash Embedding
# =========================================================


@pytest.mark.asyncio
async def test_hash_embedding_is_deterministic():
    provider = (
        HashEmbeddingProvider(
            dimension=256
        )
    )

    first = (
        await provider.embed(
            [
                "AgentMesh Runtime"
            ]
        )
    )[0]

    second = (
        await provider.embed(
            [
                "AgentMesh Runtime"
            ]
        )
    )[0]

    assert first == second

    assert (
        len(first)
        == 256
    )


@pytest.mark.asyncio
async def test_hash_embedding_is_normalized():
    provider = (
        HashEmbeddingProvider(
            dimension=128
        )
    )

    vector = (
        await provider.embed(
            [
                "adaptive scheduling"
            ]
        )
    )[0]

    norm = math.sqrt(
        sum(
            value * value
            for value
            in vector
        )
    )

    assert (
        abs(
            norm - 1.0
        )
        < 1e-6
    )


# =========================================================
# Chunking
# =========================================================


def test_chunk_text_preserves_metadata_and_overlap():
    text = (
        "A" * 600
    )

    chunks = (
        chunk_text(
            text=text,
            source="test-doc",
            metadata={
                "userId": 7
            },
            chunk_size=500,
            overlap=100,
        )
    )

    assert (
        len(chunks)
        == 2
    )

    assert (
        chunks[0]
        .metadata["userId"]
        == 7
    )

    assert (
        chunks[1]
        .metadata["start"]
        == 400
    )

    assert (
        chunks[0].id
        != chunks[1].id
    )


# =========================================================
# Fake Milvus
# =========================================================


class FakeMilvusClient:
    def __init__(
        self,
    ):
        self.upsert_rows = []

        self.search_kwargs = None

        self.delete_kwargs = None

    def has_collection(
        self,
        *,
        collection_name,
    ):
        return True

    def upsert(
        self,
        *,
        collection_name,
        data,
    ):
        self.upsert_rows.extend(
            data
        )

        return {
            "upsert_count":
                len(data)
        }

    def search(
        self,
        **kwargs,
    ):
        self.search_kwargs = (
            kwargs
        )

        return [
            [
                {
                    "id":
                        "chunk-1",

                    "distance":
                        0.91,

                    "entity": {
                        "text":
                            (
                                "AgentMesh 推荐"
                                "生产部署区域是华东。"
                            ),

                        "source":
                            "demo-doc",

                        "user_id":
                            1,

                        "metadata": {
                            "userId": 1
                        },
                    },
                }
            ]
        ]

    def delete(
        self,
        *,
        collection_name,
        filter,
    ):
        self.delete_kwargs = {
            "collection_name": collection_name,
            "filter": filter,
        }
        return {"delete_count": 1}

    def close(
        self,
    ):
        pass


@pytest.mark.asyncio
async def test_milvus_retriever_upsert_maps_document():
    embedding = (
        HashEmbeddingProvider(
            dimension=64
        )
    )

    client = (
        FakeMilvusClient()
    )

    retriever = (
        MilvusRetriever(
            uri=(
                "http://unused"
            ),

            collection_name=(
                "test_collection"
            ),

            embedding=(
                embedding
            ),

            client=(
                client
            ),
        )
    )

    count = (
        await retriever
        .upsert_documents(
            [
                RetrievalDocument(
                    id="doc-1",

                    text=(
                        "AgentMesh Runtime"
                    ),

                    source=(
                        "test"
                    ),

                    metadata={
                        "userId": 9
                    },
                )
            ]
        )
    )

    assert count == 1

    row = (
        client
        .upsert_rows[0]
    )

    assert (
        row["id"]
        == "doc-1"
    )

    assert (
        row["user_id"]
        == 9
    )

    assert (
        len(
            row["vector"]
        )
        == 64
    )


@pytest.mark.asyncio
async def test_milvus_retriever_search_uses_user_filter():
    embedding = (
        HashEmbeddingProvider(
            dimension=64
        )
    )

    client = (
        FakeMilvusClient()
    )

    retriever = (
        MilvusRetriever(
            uri=(
                "http://unused"
            ),

            collection_name=(
                "test_collection"
            ),

            embedding=(
                embedding
            ),

            client=(
                client
            ),
        )
    )

    hits = (
        await retriever.retrieve(
            (
                "AgentMesh "
                "部署在哪里？"
            ),

            top_k=3,

            filters={
                "userId": 1
            },
        )
    )

    assert (
        len(hits)
        == 1
    )

    assert (
        hits[0]
        .document
        .source
        == "demo-doc"
    )

    assert (
        hits[0].score
        == pytest.approx(
            0.91
        )
    )

    assert (
        client
        .search_kwargs[
            "filter"
        ]
        == "user_id == 1"
    )


def test_milvus_filter_combines_user_knowledge_base_and_escaped_source():
    expression = MilvusRetriever._build_filter(
        {
            "userId": 7,
            "knowledgeBaseId": 3,
            "source": 'folder\\\"quoted".md',
        }
    )

    assert "user_id == 7" in expression
    assert 'metadata["knowledgeBaseId"] == 3' in expression
    assert 'source == "folder' in expression
    assert '\\\\' in expression
    assert '\\\"' in expression


def test_milvus_filter_rejects_non_integer_knowledge_base_id():
    with pytest.raises((TypeError, ValueError)):
        MilvusRetriever._build_filter(
            {
                "userId": 7,
                "knowledgeBaseId": "not-an-id",
            }
        )


@pytest.mark.asyncio
async def test_milvus_retriever_delete_uses_schema_aware_knowledge_filter():
    embedding = HashEmbeddingProvider(dimension=64)
    client = FakeMilvusClient()
    retriever = MilvusRetriever(
        uri="http://unused",
        collection_name="test_collection",
        embedding=embedding,
        client=client,
    )

    count = await retriever.delete_documents(
        filters={
            "userId": 2,
            "knowledgeBaseId": 4,
            "knowledgeFileId": 1,
        }
    )

    assert count == 1
    assert client.delete_kwargs == {
        "collection_name": "test_collection",
        "filter": (
            'user_id == 2 and '
            'metadata["knowledgeBaseId"] == 4 and '
            'metadata["knowledgeFileId"] == 1'
        ),
    }


@pytest.mark.asyncio
async def test_milvus_retriever_delete_propagates_filter_or_provider_errors():
    class FailingMilvusClient(FakeMilvusClient):
        def delete(self, *, collection_name, filter):
            raise RuntimeError("field mismatch from milvus")

    retriever = MilvusRetriever(
        uri="http://unused",
        collection_name="test_collection",
        embedding=HashEmbeddingProvider(dimension=64),
        client=FailingMilvusClient(),
    )

    with pytest.raises(RuntimeError, match="field mismatch from milvus"):
        await retriever.delete_documents(
            filters={
                "userId": 2,
                "knowledgeBaseId": 4,
                "knowledgeFileId": 1,
            }
        )


@pytest.mark.asyncio
async def test_knowledge_indexer_delegates_delete_to_backend_filter_contract():
    class Backend:
        def __init__(self):
            self.filters = None

        async def delete_documents(self, *, filters):
            self.filters = dict(filters)
            return 1

    backend = Backend()
    indexer = KnowledgeIndexer(backend)

    await indexer.delete(
        user_id=2,
        knowledge_base_id=4,
        knowledge_file_id=1,
    )

    assert backend.filters == {
        "userId": 2,
        "knowledgeBaseId": 4,
        "knowledgeFileId": 1,
    }
