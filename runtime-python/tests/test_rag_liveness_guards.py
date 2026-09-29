from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import types
from pathlib import Path

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

        class _Placeholder:
            def __init__(self, *args, **kwargs):
                self.anns_field = kwargs.get("anns_field")
                self.filter = kwargs.get("filter")

        pymilvus_stub.AnnSearchRequest = _Placeholder
        pymilvus_stub.DataType = _DataType
        pymilvus_stub.Function = _Placeholder
        pymilvus_stub.FunctionType = _FunctionType
        pymilvus_stub.MilvusClient = _Placeholder
        pymilvus_stub.RRFRanker = _Placeholder
        sys.modules["pymilvus"] = pymilvus_stub


_install_import_stubs_when_optional_packages_are_absent()

from app.rag.embedding import OpenAICompatibleEmbeddingProvider
import app.rag.embedding as embedding_module


class _HangingEmbeddings:
    async def create(self, **kwargs):
        await asyncio.sleep(10)
        raise AssertionError("unreachable")


class _HangingOpenAIClient:
    def __init__(self) -> None:
        self.embeddings = _HangingEmbeddings()


@pytest.mark.asyncio
async def test_embedding_provider_has_hard_asyncio_deadline():
    provider = OpenAICompatibleEmbeddingProvider.__new__(
        OpenAICompatibleEmbeddingProvider
    )
    provider.dimension = 3
    provider.model = "text-embedding-test"
    provider.timeout_seconds = 0.01
    provider._client = _HangingOpenAIClient()

    with pytest.raises(TimeoutError, match="embedding request timed out"):
        await provider.embed(["hello"])


def test_embedding_client_disables_hidden_sdk_retries_and_sets_timeout(monkeypatch):
    captured: dict[str, object] = {}

    class FakeHTTPClient:
        def __init__(self, **kwargs) -> None:
            captured["http"] = kwargs

        async def aclose(self) -> None:
            return None

    class FakeOpenAI:
        def __init__(self, **kwargs) -> None:
            captured["openai"] = kwargs

    monkeypatch.setattr(embedding_module.httpx, "AsyncClient", FakeHTTPClient)
    monkeypatch.setattr(embedding_module, "AsyncOpenAI", FakeOpenAI)

    provider = OpenAICompatibleEmbeddingProvider(
        api_key="sk-test",
        base_url="https://example.invalid/v1",
        model="text-embedding-test",
        dimension=8,
        timeout_seconds=17.0,
        sdk_max_retries=0,
    )

    assert provider.timeout_seconds == 17.0
    assert captured["openai"]["timeout"] == 17.0
    assert captured["openai"]["max_retries"] == 0
    assert captured["http"]["timeout"].connect == 17.0


def _load_formal_runner():
    project_root = Path(__file__).resolve().parents[2]
    runner_path = project_root / "qa" / "rag-evaluation" / "formal_real_model_run.py"
    spec = importlib.util.spec_from_file_location("formal_real_model_run_v5", runner_path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"unable to load {runner_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_case_watchdog_fails_bounded_and_writes_case_diagnostics(tmp_path):
    runner = _load_formal_runner()
    runner.HERE = tmp_path
    ledger = runner.RetryLedger()
    ledger.current_case = "run1:multi_turn_001"
    case = {
        "case_id": "multi_turn_001",
        "category": "multi_turn_reference",
    }

    async def never_finishes():
        await asyncio.sleep(10)

    with pytest.raises(TimeoutError, match="multi_turn_001"):
        await runner.run_case_with_watchdog(
            never_finishes(),
            run_index=1,
            case=case,
            ledger=ledger,
            timeout_seconds=0.02,
        )

    diagnostic = json.loads((tmp_path / "last_case_timeout.json").read_text(encoding="utf-8"))
    assert diagnostic["reason"] == "CASE_TIMEOUT"
    assert diagnostic["case_id"] == "multi_turn_001"
    assert diagnostic["category"] == "multi_turn_reference"
    assert diagnostic["timeout_seconds"] == 0.02
    assert isinstance(diagnostic["pending_tasks"], list)


def test_checkpoint_resume_requires_same_fingerprint_and_exact_case_prefix(tmp_path):
    runner = _load_formal_runner()
    runner.HERE = tmp_path
    cases = [
        {"case_id": "a"},
        {"case_id": "b"},
        {"case_id": "c"},
    ]
    rows = [{"case_id": "a"}, {"case_id": "b"}]

    runner._write_checkpoint(
        "production_full_run1.json",
        fingerprint="same",
        rows=rows,
        status="IN_PROGRESS",
    )

    resumed = runner._load_checkpoint(
        "production_full_run1.json",
        cases=cases,
        fingerprint="same",
        allow_resume=True,
    )
    assert resumed == rows

    assert runner._load_checkpoint(
        "production_full_run1.json",
        cases=cases,
        fingerprint="different",
        allow_resume=True,
    ) == []

    payload = json.loads(
        (tmp_path / "production_full_run1.checkpoint.json").read_text(encoding="utf-8")
    )
    payload["fingerprint"] = "same"
    payload["rows"] = [{"case_id": "b"}]
    (tmp_path / "production_full_run1.checkpoint.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )
    assert runner._load_checkpoint(
        "production_full_run1.json",
        cases=cases,
        fingerprint="same",
        allow_resume=True,
    ) == []


def test_runner_help_is_real_help_not_a_formal_run(monkeypatch):
    runner = _load_formal_runner()
    with pytest.raises(SystemExit) as caught:
        runner.parse_args(["--help"])
    assert caught.value.code == 0
