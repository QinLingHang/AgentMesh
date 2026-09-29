from __future__ import annotations

import importlib.util
import sys
import time
import types

import pytest


def _install_import_stubs_when_optional_packages_are_absent() -> None:
    try:
        import openai as openai_module
        has_async_openai = hasattr(openai_module, "AsyncOpenAI")
    except Exception:
        has_async_openai = False
    if not has_async_openai:
        openai_stub = types.ModuleType("openai")

        class AsyncOpenAI:  # pragma: no cover - import-only fallback
            pass

        openai_stub.AsyncOpenAI = AsyncOpenAI
        sys.modules["openai"] = openai_stub

    if "pymilvus" not in sys.modules and importlib.util.find_spec("pymilvus") is None:
        pymilvus_stub = types.ModuleType("pymilvus")

        class _DataType:
            VARCHAR = "VARCHAR"
            INT64 = "INT64"
            JSON = "JSON"
            FLOAT_VECTOR = "FLOAT_VECTOR"
            SPARSE_FLOAT_VECTOR = "SPARSE_FLOAT_VECTOR"

        class _FunctionType:
            BM25 = "BM25"

        class AnnSearchRequest:
            def __init__(self, *args, **kwargs):
                self.anns_field = kwargs.get("anns_field")
                self.filter = kwargs.get("filter")

        class _Placeholder:
            def __init__(self, *args, **kwargs):
                pass

        pymilvus_stub.AnnSearchRequest = AnnSearchRequest
        pymilvus_stub.DataType = _DataType
        pymilvus_stub.Function = _Placeholder
        pymilvus_stub.FunctionType = _FunctionType
        pymilvus_stub.MilvusClient = _Placeholder
        pymilvus_stub.RRFRanker = _Placeholder
        sys.modules["pymilvus"] = pymilvus_stub


_install_import_stubs_when_optional_packages_are_absent()

from app.rag.embedding import HashEmbeddingProvider
from app.rag.hybrid_retriever import HybridMilvusRetriever
from app.rag.reranker import HeuristicReranker


class _SlowHybridClient:
    def __init__(self) -> None:
        self.timeout_seen = None

    def has_collection(self, *, collection_name):
        return True

    def hybrid_search(self, **kwargs):
        self.timeout_seen = kwargs.get("timeout")
        time.sleep(0.2)
        return []

    def close(self):
        pass


@pytest.mark.asyncio
async def test_hybrid_search_has_rpc_and_asyncio_deadline():
    client = _SlowHybridClient()
    retriever = HybridMilvusRetriever(
        uri="http://unused",
        collection_name="timeout_contract",
        embedding=HashEmbeddingProvider(dimension=64),
        candidate_k=1,
        reranker=HeuristicReranker(),
        fallback_reranker=HeuristicReranker(),
        client=client,
        search_timeout_seconds=0.01,
    )

    with pytest.raises(TimeoutError, match="Milvus hybrid search timed out"):
        await retriever.retrieve("lease", top_k=1, filters={"userId": 1})

    assert client.timeout_seen == 0.01
