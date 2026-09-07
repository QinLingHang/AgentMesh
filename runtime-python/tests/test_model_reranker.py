import httpx
import pytest

from app.rag import (
    QwenReranker,
    RetrievalDocument,
    RetrievalHit,
)


@pytest.mark.asyncio
async def test_qwen_reranker_reorders_documents():
    async def handler(
        request: httpx.Request,
    ) -> httpx.Response:

        body = (
            request
            .read()
            .decode(
                "utf-8"
            )
        )

        assert (
            "qwen3-rerank"
            in body
        )

        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "index": 1,
                        "relevance_score":
                            0.96,
                    },
                    {
                        "index": 0,
                        "relevance_score":
                            0.31,
                    },
                ]
            },
        )

    transport = (
        httpx.MockTransport(
            handler
        )
    )

    client = (
        httpx.AsyncClient(
            transport=transport
        )
    )

    reranker = (
        QwenReranker(
            api_key="sk-test",

            base_url=(
                "https://test.local"
            ),

            client=client,
        )
    )

    hits = [
        RetrievalHit(
            document=(
                RetrievalDocument(
                    id="architecture",
                    text=(
                        "AgentMesh supports "
                        "Dynamic DAG."
                    ),
                    source="doc-a",
                )
            ),
            score=0.9,
        ),

        RetrievalHit(
            document=(
                RetrievalDocument(
                    id="deployment",
                    text=(
                        "AgentMesh production "
                        "deployment region "
                        "is East China."
                    ),
                    source="doc-b",
                )
            ),
            score=0.8,
        ),
    ]

    result = (
        await reranker.rerank(
            (
                "Where should "
                "AgentMesh be deployed?"
            ),
            hits,
            top_k=2,
        )
    )

    assert (
        result[0]
        .document
        .id
        == "deployment"
    )

    assert (
        result[0].score
        == pytest.approx(
            0.96
        )
    )

    assert (
        result[0]
        .document
        .metadata[
            "reranker"
        ]
        == "qwen3-rerank"
    )

    assert (
        result[0]
        .document
        .metadata[
            "preRerankScore"
        ]
        == pytest.approx(
            0.8
        )
    )

    await client.aclose()


def test_qwen_reranker_rejects_non_ascii_api_key():
    with pytest.raises(
        ValueError
    ):
        QwenReranker(
            api_key=(
                "你的APIKey"
            )
        )