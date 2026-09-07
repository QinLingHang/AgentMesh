import pytest

from app.rag import (
    HashEmbeddingProvider,
    HeuristicReranker,
    HybridMilvusRetriever,
    RetrievalDocument,
    RetrievalHit,
)


@pytest.mark.asyncio
async def test_heuristic_reranker_prefers_relevant_document():
    reranker = (
        HeuristicReranker(
            rrf_weight=0.5,
            lexical_weight=0.5,
        )
    )

    hits = [
        RetrievalHit(
            document=(
                RetrievalDocument(
                    id="a",
                    text=(
                        "AgentMesh 推荐"
                        "生产部署区域是华东"
                    ),
                    source="doc-a",
                )
            ),
            score=0.9,
        ),

        RetrievalHit(
            document=(
                RetrievalDocument(
                    id="b",
                    text=(
                        "AgentMesh 使用"
                        "动态 DAG 调度"
                    ),
                    source="doc-b",
                )
            ),
            score=1.0,
        ),
    ]

    result = (
        await reranker.rerank(
            (
                "AgentMesh "
                "部署区域 华东"
            ),
            hits,
            top_k=2,
        )
    )

    assert (
        result[0]
        .document
        .id
        == "a"
    )

    assert (
        "preRerankScore"
        in result[0]
        .document
        .metadata
    )

    assert (
        "rerankScore"
        in result[0]
        .document
        .metadata
    )

    assert (
    result[0]
    .document
    .metadata[
        "reranker"
    ]
    == "heuristic"
)

    assert (
        result[0]
        .document
        .metadata[
            "preRerankScore"
        ]
        == pytest.approx(
            0.9
        )
    )


class FakeHybridMilvusClient:
    def __init__(
        self,
    ):
        self.kwargs = None

    def has_collection(
        self,
        *,
        collection_name,
    ):
        return True

    def hybrid_search(
        self,
        **kwargs,
    ):
        self.kwargs = (
            kwargs
        )

        return [
            [
                {
                    "id":
                        "deployment",

                    "distance":
                        0.032,

                    "entity": {
                        "text":
                            (
                                "AgentMesh 推荐"
                                "生产部署区域是华东"
                            ),

                        "source":
                            "deployment-doc",

                        "user_id":
                            1,

                        "metadata": {
                            "userId": 1
                        },
                    },
                },

                {
                    "id":
                        "dag",

                    "distance":
                        0.030,

                    "entity": {
                        "text":
                            (
                                "AgentMesh 支持"
                                "Dynamic DAG"
                            ),

                        "source":
                            "dag-doc",

                        "user_id":
                            1,

                        "metadata": {
                            "userId": 1
                        },
                    },
                },
            ]
        ]

    def close(
        self,
    ):
        pass


@pytest.mark.asyncio
async def test_hybrid_retriever_uses_dense_bm25_and_user_filter():
    client = (
        FakeHybridMilvusClient()
    )

    retriever = (
        HybridMilvusRetriever(
            uri="http://unused",

            collection_name=(
                "hybrid_test"
            ),

            embedding=(
                HashEmbeddingProvider(
                    dimension=64
                )
            ),

            candidate_k=5,

            client=client,
        )
    )

    hits = (
        await retriever.retrieve(
            (
                "AgentMesh "
                "部署区域在哪里"
            ),

            top_k=2,

            filters={
                "userId": 1
            },
        )
    )

    assert (
        len(hits)
        == 2
    )

    assert (
        client.kwargs
        is not None
    )

    requests = (
        client.kwargs[
            "reqs"
        ]
    )

    assert (
        len(requests)
        == 2
    )

    assert (
        requests[0]
        .anns_field
        == "vector"
    )

    assert (
        requests[1]
        .anns_field
        == "sparse"
    )

    assert (
        requests[0]
        .filter
        == "user_id == 1"
    )

    assert (
        requests[1]
        .filter
        == "user_id == 1"
    )

    assert (
        hits[0]
        .document
        .metadata[
            "retrievalMode"
        ]
        == "dense+bm25+rrf"
    )


@pytest.mark.asyncio
async def test_hybrid_retriever_respects_top_k():
    client = (
        FakeHybridMilvusClient()
    )

    retriever = (
        HybridMilvusRetriever(
            uri="http://unused",

            collection_name=(
                "hybrid_test"
            ),

            embedding=(
                HashEmbeddingProvider(
                    dimension=64
                )
            ),

            candidate_k=8,

            client=client,
        )
    )

    result = (
        await retriever.retrieve(
            "AgentMesh",
            top_k=1,
            filters={
                "userId": 1
            },
        )
    )

    assert (
        len(result)
        == 1
    )

class FailingReranker:
    name = "failing-model"

    async def rerank(
        self,
        query,
        hits,
        *,
        top_k,
    ):
        raise RuntimeError(
            "model unavailable"
        )


@pytest.mark.asyncio
async def test_hybrid_rag_falls_back_when_model_reranker_fails():
    client = (
        FakeHybridMilvusClient()
    )

    retriever = (
        HybridMilvusRetriever(
            uri="http://unused",

            collection_name=(
                "hybrid_test"
            ),

            embedding=(
                HashEmbeddingProvider(
                    dimension=64
                )
            ),

            candidate_k=5,

            reranker=(
                FailingReranker()
            ),

            fallback_reranker=(
                HeuristicReranker()
            ),

            client=client,
        )
    )

    hits = (
        await retriever.retrieve(
            (
                "AgentMesh "
                "部署区域在哪里"
            ),

            top_k=2,

            filters={
                "userId": 1
            },
        )
    )

    assert (
        len(hits)
        == 2
    )

    diagnostics = (
        hits[0]
        .document
        .metadata[
            "ragDiagnostics"
        ]
    )

    assert (
        diagnostics[
            "rerankFallback"
        ]
        is True
    )

    assert (
        diagnostics[
            "requestedReranker"
        ]
        == "failing-model"
    )

    assert (
        diagnostics[
            "effectiveReranker"
        ]
        == "heuristic"
    )

    assert (
        "RuntimeError"
        in diagnostics[
            "rerankError"
        ]
    )