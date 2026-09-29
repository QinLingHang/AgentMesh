from __future__ import annotations

import httpx
import pytest

from app.rag.embedding import HashEmbeddingProvider
from app.rag.hybrid_retriever import HybridMilvusRetriever
from app.rag.reranker import HeuristicReranker, QwenReranker
from app.rag.runtime import RetrievalDocument, RetrievalHit


def _hits() -> list[RetrievalHit]:
    return [
        RetrievalHit(
            document=RetrievalDocument(
                id="doc-1",
                text="AgentMesh lease and fencing policy.",
                source="unit-test",
                metadata={},
            ),
            score=0.8,
        )
    ]


def _success(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        request=request,
        json={
            "results": [
                {
                    "index": 0,
                    "relevance_score": 0.95,
                }
            ]
        },
    )


@pytest.mark.asyncio
async def test_qwen_reranker_retries_connect_error_then_recovers():
    calls = 0
    sleeps: list[float] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("temporary", request=request)
        return _success(request)

    async def sleeper(delay: float) -> None:
        sleeps.append(delay)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    reranker = QwenReranker(
        api_key="sk-test",
        base_url="https://test.local",
        client=client,
        sleeper=sleeper,
    )

    result = await reranker.rerank("lease", _hits(), top_k=1)

    assert calls == 2
    assert sleeps == [2.0]
    metadata = result[0].document.metadata
    assert metadata["rerankAttempts"] == 2
    assert metadata["rerankRetries"] == 1
    assert metadata["rerankRecovered"] is True
    await client.aclose()


@pytest.mark.asyncio
async def test_qwen_reranker_retries_503_with_fixed_backoff():
    calls = 0
    sleeps: list[float] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            return httpx.Response(503, request=request, text="temporary")
        return _success(request)

    async def sleeper(delay: float) -> None:
        sleeps.append(delay)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    reranker = QwenReranker(
        api_key="sk-test",
        base_url="https://test.local",
        client=client,
        sleeper=sleeper,
    )

    result = await reranker.rerank("lease", _hits(), top_k=1)

    assert calls == 3
    assert sleeps == [2.0, 4.0]
    assert result[0].document.metadata["rerankAttempts"] == 3
    assert result[0].document.metadata["rerankRetries"] == 2
    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403])
async def test_qwen_reranker_does_not_retry_deterministic_http_errors(status: int):
    calls = 0
    sleeps: list[float] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, request=request, text="bad request")

    async def sleeper(delay: float) -> None:
        sleeps.append(delay)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    reranker = QwenReranker(
        api_key="sk-test",
        base_url="https://test.local",
        client=client,
        sleeper=sleeper,
    )

    with pytest.raises(httpx.HTTPStatusError) as caught:
        await reranker.rerank("lease", _hits(), top_k=1)

    assert calls == 1
    assert sleeps == []
    assert getattr(caught.value, "agentmesh_rerank_attempts") == 1
    assert getattr(caught.value, "agentmesh_rerank_retryable") is False
    await client.aclose()


@pytest.mark.asyncio
async def test_qwen_reranker_exhausts_three_transient_attempts():
    calls = 0
    sleeps: list[float] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("temporary", request=request)

    async def sleeper(delay: float) -> None:
        sleeps.append(delay)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    reranker = QwenReranker(
        api_key="sk-test",
        base_url="https://test.local",
        client=client,
        sleeper=sleeper,
    )

    with pytest.raises(httpx.ConnectError) as caught:
        await reranker.rerank("lease", _hits(), top_k=1)

    assert calls == 3
    assert sleeps == [2.0, 4.0]
    assert getattr(caught.value, "agentmesh_rerank_attempts") == 3
    assert getattr(caught.value, "agentmesh_rerank_retries") == 2
    assert getattr(caught.value, "agentmesh_rerank_retryable") is True
    await client.aclose()


@pytest.mark.asyncio
async def test_qwen_reranker_first_call_success_does_not_retry():
    calls = 0
    sleeps: list[float] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _success(request)

    async def sleeper(delay: float) -> None:
        sleeps.append(delay)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    reranker = QwenReranker(
        api_key="sk-test",
        base_url="https://test.local",
        client=client,
        sleeper=sleeper,
    )

    result = await reranker.rerank("lease", _hits(), top_k=1)

    assert calls == 1
    assert sleeps == []
    assert result[0].document.metadata["rerankAttempts"] == 1
    assert result[0].document.metadata["rerankRetries"] == 0
    assert result[0].document.metadata["rerankRecovered"] is False
    await client.aclose()


@pytest.mark.asyncio
async def test_qwen_reranker_retries_429_then_recovers():
    calls = 0
    sleeps: list[float] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, request=request, text="rate limited")
        return _success(request)

    async def sleeper(delay: float) -> None:
        sleeps.append(delay)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    reranker = QwenReranker(
        api_key="sk-test",
        base_url="https://test.local",
        client=client,
        sleeper=sleeper,
    )

    result = await reranker.rerank("lease", _hits(), top_k=1)

    assert calls == 2
    assert sleeps == [2.0]
    assert result[0].document.metadata["rerankRecovered"] is True
    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error_factory",
    [
        lambda request: httpx.ConnectTimeout("temporary", request=request),
        lambda request: httpx.ReadTimeout("temporary", request=request),
        lambda request: httpx.RemoteProtocolError("temporary", request=request),
        lambda request: ConnectionResetError("temporary"),
    ],
    ids=[
        "connect-timeout",
        "read-timeout",
        "remote-protocol",
        "connection-reset",
    ],
)
async def test_qwen_reranker_retries_supported_transient_errors(error_factory):
    calls = 0
    sleeps: list[float] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise error_factory(request)
        return _success(request)

    async def sleeper(delay: float) -> None:
        sleeps.append(delay)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    reranker = QwenReranker(
        api_key="sk-test",
        base_url="https://test.local",
        client=client,
        sleeper=sleeper,
    )

    result = await reranker.rerank("lease", _hits(), top_k=1)

    assert calls == 2
    assert sleeps == [2.0]
    assert result[0].document.metadata["rerankAttempts"] == 2
    assert result[0].document.metadata["rerankRetries"] == 1
    assert result[0].document.metadata["rerankRecovered"] is True
    await client.aclose()


class _FakeHybridMilvusClient:
    def has_collection(self, *, collection_name):
        return True

    def hybrid_search(self, **kwargs):
        return [
            [
                {
                    "id": "doc-1",
                    "distance": 0.031,
                    "entity": {
                        "text": "AgentMesh lease and fencing policy.",
                        "source": "unit-test",
                        "user_id": 1,
                        "metadata": {"userId": 1},
                    },
                }
            ]
        ]

    def close(self):
        pass


def _copy_hit_with_rerank_metadata(
    hit: RetrievalHit,
    *,
    attempts: int,
    retries: int,
    recovered: bool,
) -> RetrievalHit:
    return RetrievalHit(
        document=RetrievalDocument(
            id=hit.document.id,
            text=hit.document.text,
            source=hit.document.source,
            metadata={
                **hit.document.metadata,
                "reranker": "qwen3-rerank",
                "rerankAttempts": attempts,
                "rerankRetries": retries,
                "rerankRecovered": recovered,
            },
        ),
        score=0.97,
    )


class _RecoveredModelReranker:
    name = "qwen3-rerank"

    async def rerank(self, query, hits, *, top_k):
        return [
            _copy_hit_with_rerank_metadata(
                hits[0],
                attempts=2,
                retries=1,
                recovered=True,
            )
        ]


class _FailingModelReranker:
    name = "qwen3-rerank"

    def __init__(
        self,
        exc: Exception,
        *,
        attempts: int,
        retries: int,
        retryable: bool,
    ) -> None:
        self.exc = exc
        setattr(exc, "agentmesh_rerank_attempts", attempts)
        setattr(exc, "agentmesh_rerank_retries", retries)
        setattr(exc, "agentmesh_rerank_retryable", retryable)

    async def rerank(self, query, hits, *, top_k):
        raise self.exc


def _hybrid_retriever(reranker) -> HybridMilvusRetriever:
    return HybridMilvusRetriever(
        uri="http://unused",
        collection_name="hybrid_retry_diagnostics",
        embedding=HashEmbeddingProvider(dimension=64),
        candidate_k=1,
        reranker=reranker,
        fallback_reranker=HeuristicReranker(),
        client=_FakeHybridMilvusClient(),
    )


@pytest.mark.asyncio
async def test_hybrid_retriever_propagates_recovered_retry_diagnostics():
    retriever = _hybrid_retriever(_RecoveredModelReranker())

    hits = await retriever.retrieve(
        "lease",
        top_k=1,
        filters={"userId": 1},
    )

    diagnostics = hits[0].document.metadata["ragDiagnostics"]
    assert diagnostics["requestedReranker"] == "qwen3-rerank"
    assert diagnostics["effectiveReranker"] == "qwen3-rerank"
    assert diagnostics["rerankFallback"] is False
    assert diagnostics["rerankAttempts"] == 2
    assert diagnostics["rerankRetries"] == 1
    assert diagnostics["rerankRecovered"] is True
    assert diagnostics["rerankFailureRetryable"] is False


@pytest.mark.asyncio
async def test_hybrid_retriever_reports_deterministic_failure_fallback_diagnostics():
    request = httpx.Request("POST", "https://test.local/reranks")
    response = httpx.Response(401, request=request, text="unauthorized")
    exc = httpx.HTTPStatusError(
        "unauthorized",
        request=request,
        response=response,
    )
    retriever = _hybrid_retriever(
        _FailingModelReranker(
            exc,
            attempts=1,
            retries=0,
            retryable=False,
        )
    )

    hits = await retriever.retrieve(
        "lease",
        top_k=1,
        filters={"userId": 1},
    )

    diagnostics = hits[0].document.metadata["ragDiagnostics"]
    assert diagnostics["requestedReranker"] == "qwen3-rerank"
    assert diagnostics["effectiveReranker"] == "heuristic"
    assert diagnostics["rerankFallback"] is True
    assert diagnostics["rerankAttempts"] == 1
    assert diagnostics["rerankRetries"] == 0
    assert diagnostics["rerankRecovered"] is False
    assert diagnostics["rerankFailureRetryable"] is False
    assert diagnostics["rerankErrorType"] == "HTTPStatusError"


@pytest.mark.asyncio
async def test_hybrid_retriever_reports_retry_exhaustion_fallback_diagnostics():
    request = httpx.Request("POST", "https://test.local/reranks")
    exc = httpx.ConnectError("temporary", request=request)
    retriever = _hybrid_retriever(
        _FailingModelReranker(
            exc,
            attempts=3,
            retries=2,
            retryable=True,
        )
    )

    hits = await retriever.retrieve(
        "lease",
        top_k=1,
        filters={"userId": 1},
    )

    diagnostics = hits[0].document.metadata["ragDiagnostics"]
    assert diagnostics["requestedReranker"] == "qwen3-rerank"
    assert diagnostics["effectiveReranker"] == "heuristic"
    assert diagnostics["rerankFallback"] is True
    assert diagnostics["rerankAttempts"] == 3
    assert diagnostics["rerankRetries"] == 2
    assert diagnostics["rerankRecovered"] is False
    assert diagnostics["rerankFailureRetryable"] is True
    assert diagnostics["rerankErrorType"] == "ConnectError"
