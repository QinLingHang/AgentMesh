#!/usr/bin/env python3
"""Formal frozen-corpus retrieval evaluation using AgentMesh production RAG components."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import statistics
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Awaitable

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "runtime-python"))

EXPECTED_CORPUS = "ff287c111a5b2fff9a6b70bb185f7cafd0e603dae924ada556a3295b8353ddd2"
EXPECTED_BENCH = "6e445d7458ce5776bb702d32ee7af6cd9423c69992d2fd7c5a4177ccf9a4d029"
TOP_K = 10
CASE_TIMEOUT_SECONDS = 240.0
EMBEDDING_TIMEOUT_SECONDS = 20.0
MILVUS_RPC_TIMEOUT_SECONDS = 10.0
SMOKE_BOUNDARY_CASE_IDS = (
    "multi_evidence_014",
    "multi_evidence_015",
    "multi_turn_001",
    "multi_turn_002",
    "multi_turn_003",
)


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def error_kind(exc: BaseException) -> tuple[str, bool]:
    status = (
        getattr(getattr(exc, "response", None), "status_code", None)
        or getattr(exc, "status_code", None)
    )
    name = type(exc).__name__
    text = f"{name} {exc}".lower()
    if status == 429:
        return "429", True
    if status is not None and 500 <= status <= 599:
        return "5xx", True
    if name in {"ConnectError", "APIConnectionError"} or "connection reset" in text or "temporary network" in text:
        return "ConnectError", True
    if name in {"ConnectTimeout", "APITimeoutError"} or "connect timeout" in text:
        return "ConnectTimeout", True
    if name in {"ReadTimeout", "TimeoutError"} or "read timeout" in text or "timed out" in text:
        return "ReadTimeout", True
    if name == "RemoteProtocolError":
        return "RemoteProtocolError", True
    return "Other", False


class RetryLedger:
    def __init__(self) -> None:
        self.external_calls = 0
        self.logical_calls = 0
        self.first_attempt_successes = 0
        self.retries: Counter[str] = Counter()
        self.errors: Counter[str] = Counter()
        self.retry_cases: set[str] = set()
        self.current_case = ""
        self.current_stage = ""
        self.case_overhead: defaultdict[str, float] = defaultdict(float)

    def snapshot(self) -> dict[str, Any]:
        return {
            "external_calls": self.external_calls,
            "logical_calls": self.logical_calls,
            "first_attempt_successes": self.first_attempt_successes,
            "retries": dict(self.retries),
            "errors": dict(self.errors),
            "case_overhead_ms": float(self.case_overhead[self.current_case]),
        }

    def delta(self, before: dict[str, Any]) -> dict[str, Any]:
        retry_before = Counter(before.get("retries") or {})
        error_before = Counter(before.get("errors") or {})
        retry_delta = Counter({
            key: self.retries[key] - retry_before[key]
            for key in set(self.retries) | set(retry_before)
            if self.retries[key] - retry_before[key]
        })
        error_delta = Counter({
            key: self.errors[key] - error_before[key]
            for key in set(self.errors) | set(error_before)
            if self.errors[key] - error_before[key]
        })
        return {
            "external_calls": self.external_calls - int(before.get("external_calls", 0)),
            "logical_calls": self.logical_calls - int(before.get("logical_calls", 0)),
            "first_attempt_successes": self.first_attempt_successes - int(before.get("first_attempt_successes", 0)),
            "retry_by_stage": dict(retry_delta),
            "errors_by_type": dict(error_delta),
            "retry_count": sum(retry_delta.values()),
            "retry_overhead_ms": float(self.case_overhead[self.current_case]) - float(before.get("case_overhead_ms", 0.0)),
        }

    async def call(self, stage: str, operation) -> Any:
        self.logical_calls += 1
        started = time.perf_counter()
        for attempt in range(1, 4):
            self.external_calls += 1
            self.current_stage = stage
            attempt_started = time.perf_counter()
            try:
                value = await operation()
                success_ms = (time.perf_counter() - attempt_started) * 1000
                if attempt == 1:
                    self.first_attempt_successes += 1
                if attempt > 1:
                    self.case_overhead[self.current_case] += (
                        (time.perf_counter() - started) * 1000 - success_ms
                    )
                self.current_stage = ""
                return value
            except Exception as exc:
                kind, retryable = error_kind(exc)
                self.errors[kind] += 1
                emit({
                    "stage": "external_call",
                    "event": "failure",
                    "case": self.current_case,
                    "operation": stage,
                    "attempt": attempt,
                    "error_type": kind,
                    "exception": type(exc).__name__,
                    "retryable": retryable,
                })
                if not retryable or attempt == 3:
                    self.current_stage = ""
                    raise
                self.retries[stage] += 1
                self.retry_cases.add(self.current_case)
                delay = 2 if attempt == 1 else 4
                emit({
                    "stage": "external_call",
                    "event": "retry",
                    "case": self.current_case,
                    "operation": stage,
                    "next_attempt": attempt + 1,
                    "delay_seconds": delay,
                })
                await asyncio.sleep(delay)
        raise AssertionError("unreachable retry state")


class RetryEmbedding:
    def __init__(self, inner, ledger: RetryLedger) -> None:
        self.inner = inner
        self.ledger = ledger
        self.dimension = inner.dimension

    async def embed(self, texts):
        return await self.ledger.call("embedding", lambda: self.inner.embed(texts))

    async def aclose(self) -> None:
        await self.inner.aclose()


class RetryReranker:
    name = "qwen3-rerank"

    def __init__(self, inner, ledger: RetryLedger) -> None:
        self.inner = inner
        self.ledger = ledger

    async def rerank(self, query, hits, *, top_k):
        return await self.ledger.call(
            "reranker",
            lambda: self.inner.rerank(query, hits, top_k=top_k),
        )

    async def aclose(self) -> None:
        await self.inner.aclose()


def dump(name: str, obj: Any) -> None:
    (HERE / name).write_text(
        json.dumps(obj, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def pct(xs, p):
    if not xs:
        return None
    a = sorted(xs)
    x = (len(a) - 1) * p
    lo = int(x)
    hi = min(lo + 1, len(a) - 1)
    return a[lo] + (a[hi] - a[lo]) * (x - lo)


def validate():
    done = subprocess.run(
        [sys.executable, str(HERE / "validate_benchmark.py")],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    if done.returncode:
        raise RuntimeError(done.stdout + done.stderr)
    value = json.loads(done.stdout)
    if value["corpus_sha256"] != EXPECTED_CORPUS or value["benchmark_sha256"] != EXPECTED_BENCH:
        raise RuntimeError("frozen SHA mismatch")
    return value


def load():
    manifest = json.loads((HERE / "corpus_manifest.json").read_text(encoding="utf-8"))
    cases = [
        json.loads(line)
        for line in (HERE / "benchmark.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    return manifest, cases


class TimedModel:
    def __init__(self, gateway, model_name: str, ledger: RetryLedger) -> None:
        self.gateway = gateway
        self.model_name = model_name
        self.ledger = ledger
        self.calls: list[dict[str, Any]] = []

    async def generate(self, prompt: str, on_event=None):
        from app.models.contracts import ModelMessage, ModelRequest

        kind = (
            "evidence_grading"
            if "[evidence]" in prompt
            else (
                "rewrite"
                if "[operation]\nrewrite" in prompt
                else ("multi_query" if "[operation]\nmulti_query" in prompt else "decomposition")
            )
        )
        started = time.perf_counter()
        response = await self.ledger.call(
            kind,
            lambda: self.gateway.generate(
                ModelRequest(
                    model=self.model_name,
                    messages=[ModelMessage(role="user", content=prompt)],
                    temperature=0,
                    max_tokens=500,
                ),
                on_event,
            ),
        )
        self.calls.append({
            "kind": kind,
            "latency_ms": (time.perf_counter() - started) * 1000,
            "provider": response.provider,
            "model": response.model,
        })
        if response.provider == "mock":
            raise RuntimeError("mock model response forbidden")
        return response.content


def query_for(case):
    history = case.get("conversation_history") or []
    if not history:
        return case["query"]
    return "\n".join(
        [f"Previous user turn: {item['content']}" for item in history]
        + [f"Current user turn: {case['query']}"]
    )


def row_metrics(row):
    if not row["answerable"]:
        return None
    gold = set(row["gold_chunk_ids"])
    got = row["retrieved_chunk_ids"]

    def recall(k):
        return len(gold & set(got[:k])) / len(gold)

    ranks = [i for i, item in enumerate(got[:10], 1) if item in gold]
    dcg = sum(1 / math.log2(i + 1) for i in ranks)
    ideal = sum(1 / math.log2(i + 1) for i in range(1, min(len(gold), 10) + 1))
    return {
        "recall_at_5": recall(5),
        "recall_at_10": recall(10),
        "hit_at_5": float(bool(gold & set(got[:5]))),
        "mrr_at_10": 1 / min(ranks) if ranks else 0.0,
        "ndcg_at_10": dcg / ideal if ideal else 0.0,
    }


def aggregate(rows):
    positives = [row for row in rows if row["answerable"]]
    negatives = [row for row in rows if not row["answerable"]]
    keys = ["recall_at_5", "recall_at_10", "hit_at_5", "mrr_at_10", "ndcg_at_10"]
    out = {key: statistics.fmean(row["metrics"][key] for row in positives) for key in keys}
    out["negative_evidence_error_rate"] = statistics.fmean(
        float(row.get("evidence_sufficient", False)) for row in negatives
    ) if negatives else 0.0
    out["latency_ms"] = {
        "p50": pct([row["latency_ms"] for row in rows], 0.5),
        "p95": pct([row["latency_ms"] for row in rows], 0.95),
    }
    by = {}
    for category in sorted({row["category"] for row in positives}):
        group = [row for row in positives if row["category"] == category]
        by[category] = {key: statistics.fmean(row["metrics"][key] for row in group) for key in keys}
    out["by_category"] = by
    return out


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evaluation_fingerprint(settings) -> str:
    files = [
        Path(__file__).resolve(),
        ROOT / "runtime-python/app/rag/embedding.py",
        ROOT / "runtime-python/app/rag/hybrid_retriever.py",
        ROOT / "runtime-python/app/rag/model_intelligence.py",
        ROOT / "runtime-python/app/rag/reranker.py",
        ROOT / "runtime-python/app/rag/agentic_retrieval.py",
        ROOT / "runtime-python/app/rag/adaptive_router.py",
    ]
    payload = {
        "files": {str(path.relative_to(ROOT)): _sha256_file(path) for path in files},
        "corpus": EXPECTED_CORPUS,
        "benchmark": EXPECTED_BENCH,
        "top_k": TOP_K,
        "embedding_model": settings.embedding_model,
        "embedding_dimension": 256,
        "model_name": settings.model_name,
        "reranker_model": settings.reranker_model,
        "candidate_k": settings.rag_candidate_k,
        "rrf_k": settings.rag_rrf_k,
        "collection": settings.milvus_hybrid_collection,
        "embedding_timeout_seconds": EMBEDDING_TIMEOUT_SECONDS,
        "milvus_rpc_timeout_seconds": MILVUS_RPC_TIMEOUT_SECONDS,
        "model_timeout_seconds": settings.model_timeout_seconds,
        "reranker_timeout_seconds": settings.reranker_timeout_seconds,
        "case_timeout_seconds": CASE_TIMEOUT_SECONDS,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _task_stack(task: asyncio.Task[Any]) -> list[str]:
    rows: list[str] = []
    try:
        for frame in task.get_stack(limit=20):
            rows.append(f"{frame.f_code.co_filename}:{frame.f_lineno} in {frame.f_code.co_name}")
    except Exception as exc:
        rows.append(f"stack unavailable: {type(exc).__name__}: {exc}")
    return rows


def _pending_task_snapshot() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    current = asyncio.current_task()
    for task in asyncio.all_tasks():
        if task is current or task.done():
            continue
        result.append({
            "name": task.get_name(),
            "stack": _task_stack(task),
        })
    return result[:50]


async def run_case_with_watchdog(
    operation: Awaitable[Any],
    *,
    run_index: int,
    case: dict[str, Any],
    ledger: RetryLedger,
    timeout_seconds: float = CASE_TIMEOUT_SECONDS,
):
    task = asyncio.create_task(
        operation,
        name=f"rag-eval-run{run_index}-{case['case_id']}",
    )
    done, _ = await asyncio.wait({task}, timeout=timeout_seconds)
    if task in done:
        return task.result()

    diagnostic = {
        "status": "BLOCKED",
        "reason": "CASE_TIMEOUT",
        "run": run_index,
        "case_id": case["case_id"],
        "category": case["category"],
        "timeout_seconds": timeout_seconds,
        "last_external_stage": ledger.current_stage or None,
        "case_task_stack": _task_stack(task),
        "pending_tasks": _pending_task_snapshot(),
        "timestamp": time.time(),
    }
    dump("last_case_timeout.json", diagnostic)
    emit({
        "stage": f"full_run{run_index}" if run_index else "smoke_boundary",
        "event": "case_timeout",
        "case_id": case["case_id"],
        "category": case["category"],
        "timeout_seconds": timeout_seconds,
        "last_external_stage": ledger.current_stage or None,
        "diagnostic": str(HERE / "last_case_timeout.json"),
    })
    task.cancel()
    try:
        await asyncio.wait_for(task, timeout=5.0)
    except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
        pass
    raise TimeoutError(
        f"RAG case {case['case_id']} timed out after {timeout_seconds:.1f}s"
    )


def _checkpoint_path(artifact_name: str) -> Path:
    stem = Path(artifact_name).stem
    return HERE / f"{stem}.checkpoint.json"


def _load_checkpoint(
    artifact_name: str,
    *,
    cases: list[dict[str, Any]],
    fingerprint: str,
    allow_resume: bool,
) -> list[dict[str, Any]]:
    if not allow_resume:
        return []
    path = _checkpoint_path(artifact_name)
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = list(payload.get("rows") or [])
        if payload.get("fingerprint") != fingerprint:
            emit({"stage": "checkpoint", "event": "ignored", "reason": "fingerprint_mismatch", "path": str(path)})
            return []
        if len(rows) > len(cases):
            emit({"stage": "checkpoint", "event": "ignored", "reason": "row_count_invalid", "path": str(path)})
            return []
        expected = [case["case_id"] for case in cases[: len(rows)]]
        actual = [row.get("case_id") for row in rows]
        if actual != expected:
            emit({"stage": "checkpoint", "event": "ignored", "reason": "case_prefix_mismatch", "path": str(path)})
            return []
        if rows:
            emit({
                "stage": "checkpoint",
                "event": "resume",
                "completed": len(rows),
                "next_case": cases[len(rows)]["case_id"] if len(rows) < len(cases) else None,
                "path": str(path),
            })
        return rows
    except Exception as exc:
        emit({
            "stage": "checkpoint",
            "event": "ignored",
            "reason": f"{type(exc).__name__}: {exc}",
            "path": str(path),
        })
        return []


def _write_checkpoint(
    artifact_name: str,
    *,
    fingerprint: str,
    rows: list[dict[str, Any]],
    status: str,
    failure: dict[str, Any] | None = None,
) -> None:
    payload = {
        "status": status,
        "fingerprint": fingerprint,
        "corpus_sha256": EXPECTED_CORPUS,
        "benchmark_sha256": EXPECTED_BENCH,
        "top_k": TOP_K,
        "completed": len(rows),
        "rows": rows,
        "failure": failure,
    }
    dump(_checkpoint_path(artifact_name).name, payload)


async def build_collection(manifest, embedding, settings):
    from app.rag.hybrid_retriever import HybridMilvusRetriever
    from app.rag.runtime import RetrievalDocument
    from app.rag.reranker import QwenReranker
    from pymilvus import MilvusClient

    name = settings.milvus_hybrid_collection
    if name != "agentmesh_rag_eval_ff287c111a5b":
        raise RuntimeError("unexpected evaluation collection")
    client = MilvusClient(uri=settings.milvus_uri, timeout=MILVUS_RPC_TIMEOUT_SECONDS)
    reranker = QwenReranker(
        api_key=settings.reranker_api_key,
        base_url=settings.reranker_base_url,
        model=settings.reranker_model,
        timeout_seconds=settings.reranker_timeout_seconds,
        trust_env=settings.reranker_http_trust_env,
        instruct=settings.reranker_instruct,
    )
    retriever = HybridMilvusRetriever(
        uri=settings.milvus_uri,
        collection_name=name,
        embedding=embedding,
        candidate_k=settings.rag_candidate_k,
        rrf_k=settings.rag_rrf_k,
        reranker=reranker,
        client=client,
        search_timeout_seconds=MILVUS_RPC_TIMEOUT_SECONDS,
    )
    docs = [
        RetrievalDocument(
            id=item["chunk_id"],
            text=item["text"],
            source=item["source"],
            metadata={**item["metadata"], "corpusSha256": EXPECTED_CORPUS},
        )
        for item in manifest["chunks"]
    ]
    if client.has_collection(collection_name=name, timeout=MILVUS_RPC_TIMEOUT_SECONDS):
        existing = client.query(
            collection_name=name,
            filter="",
            output_fields=["count(*)"],
            timeout=MILVUS_RPC_TIMEOUT_SECONDS,
        )[0]["count(*)"]
        probe = client.query(
            collection_name=name,
            filter="",
            output_fields=["id", "metadata"],
            limit=10,
            timeout=MILVUS_RPC_TIMEOUT_SECONDS,
        )
        if int(existing) == 210 and len(probe) == 10 and all(
            (item.get("metadata") or {}).get("corpusSha256") == EXPECTED_CORPUS
            for item in probe
        ):
            return client, retriever, {
                "collection": name,
                "documents": 30,
                "chunks": 210,
                "sampled": 10,
                "reused": True,
            }
        client.drop_collection(collection_name=name, timeout=MILVUS_RPC_TIMEOUT_SECONDS)

    inserted = 0
    for index in range(0, len(docs), 10):
        inserted += await retriever.upsert_documents(docs[index : index + 10])
    client.flush(collection_name=name, timeout=MILVUS_RPC_TIMEOUT_SECONDS)
    count = client.query(
        collection_name=name,
        filter="",
        output_fields=["count(*)"],
        timeout=MILVUS_RPC_TIMEOUT_SECONDS,
    )[0]["count(*)"]
    sample_ids = sorted(item.id for item in docs)[:10]
    sample = client.query(
        collection_name=name,
        filter="id in [" + ",".join(json.dumps(item) for item in sample_ids) + "]",
        output_fields=["id", "user_id", "metadata"],
        limit=10,
        timeout=MILVUS_RPC_TIMEOUT_SECONDS,
    )
    expected = {item.id: item for item in docs}
    checked = 0
    for item in sample:
        expected_item = expected[str(item["id"])]
        metadata = item.get("metadata") or {}
        if (
            metadata.get("documentId") != expected_item.metadata.get("documentId")
            or int(item.get("user_id")) != 7001
            or metadata.get("projectId") != 9001
        ):
            raise RuntimeError("Milvus metadata sample mismatch")
        checked += 1
    if inserted != 210 or int(count) != 210 or checked < 10:
        raise RuntimeError(
            f"collection validation failed inserted={inserted} count={count} checked={checked}"
        )
    return client, retriever, {
        "collection": name,
        "documents": 30,
        "chunks": int(count),
        "sampled": checked,
    }


async def baseline(cases, settings, embedding, client):
    rows = []
    for index, case in enumerate(cases, 1):
        started = time.perf_counter()
        vector = (await embedding.embed([query_for(case)]))[0]
        found = await asyncio.wait_for(
            asyncio.to_thread(
                client.search,
                collection_name=settings.milvus_hybrid_collection,
                data=[vector],
                anns_field="vector",
                limit=TOP_K,
                filter="user_id == 7001",
                output_fields=["text", "source", "user_id", "metadata"],
                search_params={"metric_type": "COSINE", "params": {}},
                timeout=MILVUS_RPC_TIMEOUT_SECONDS,
            ),
            timeout=MILVUS_RPC_TIMEOUT_SECONDS + 2.0,
        )
        hits = found[0] if found else []
        latency = (time.perf_counter() - started) * 1000
        row = {
            **{key: case[key] for key in ["case_id", "category", "answerable", "gold_chunk_ids"]},
            "query": case["query"],
            "retrieved_chunk_ids": [str(hit.get("id", "")) for hit in hits],
            "hits": [
                {"chunk_id": str(hit.get("id", "")), "rank": rank, "score": float(hit.get("distance", 0))}
                for rank, hit in enumerate(hits, 1)
            ],
            "latency_ms": latency,
            "evidence_sufficient": False,
        }
        row["metrics"] = row_metrics(row)
        rows.append(row)
        if index % 20 == 0:
            emit({"stage": "baseline", "completed": index, "total": len(cases)})
    result = {
        "status": "PASS",
        "pipeline": "VECTOR_BASELINE",
        "top_k": TOP_K,
        "rows": rows,
        "metrics": aggregate(rows),
    }
    dump("vector_baseline_results.json", result)
    return result


def aggregate_retry_statistics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_stage: Counter[str] = Counter()
    by_error: Counter[str] = Counter()
    external_calls = 0
    logical_calls = 0
    first_attempt_successes = 0
    retry_cases = 0
    total_retries = 0
    for row in rows:
        external_calls += int(row.get("external_calls", 0))
        logical_calls += int(row.get("logical_calls", 0))
        first_attempt_successes += int(row.get("first_attempt_successes", 0))
        retries = int(row.get("retry_count", 0))
        total_retries += retries
        if retries:
            retry_cases += 1
        by_stage.update(row.get("retry_by_stage") or {})
        by_error.update(row.get("errors_by_type") or {})
    return {
        "external_model_calls": external_calls,
        "cases_requiring_retry": retry_cases,
        "total_retries": total_retries,
        "by_stage": dict(by_stage),
        "by_error": dict(by_error),
        "first_attempt_success_rate": first_attempt_successes / max(1, logical_calls),
    }


async def full_run(
    run_index,
    cases,
    settings,
    hybrid,
    model,
    ledger,
    *,
    artifact_name: str | None = None,
    allow_resume: bool = True,
    stage_name: str | None = None,
):
    from app.rag.adaptive_router import AdaptiveRAGRouter
    from app.rag.agentic_retrieval import AgenticRetrievalExecutor
    from app.rag.model_intelligence import ModelBackedEvidenceGrader, ModelBackedQueryTransformer

    artifact_name = artifact_name or f"production_full_run{run_index}.json"
    stage_name = stage_name or f"full_run{run_index}"
    fingerprint = evaluation_fingerprint(settings)
    fallback: list[dict[str, Any]] = []

    def event(payload):
        if payload.get("fallback"):
            fallback.append(payload)

    executor = AgenticRetrievalExecutor(
        retriever=hybrid,
        transformer=ModelBackedQueryTransformer(model=model, on_rag_event=event),
        grader=ModelBackedEvidenceGrader(model=model, on_rag_event=event),
    )
    router = AdaptiveRAGRouter()
    rows = _load_checkpoint(
        artifact_name,
        cases=cases,
        fingerprint=fingerprint,
        allow_resume=allow_resume,
    )

    for index, case in enumerate(cases, 1):
        if index <= len(rows):
            continue
        ledger.current_case = f"run{run_index}:{case['case_id']}" if run_index else f"smoke:{case['case_id']}"
        case_key = ledger.current_case
        q = query_for(case)
        decision = router.route(q, capabilities=("knowledge",))
        before_model_calls = len(model.calls)
        before_ledger = ledger.snapshot()
        fallback_before = len(fallback)
        started = time.perf_counter()
        emit({
            "stage": stage_name,
            "event": "case_start",
            "index": index,
            "total": len(cases),
            "case_id": case["case_id"],
            "category": case["category"],
            "route": decision.mode.value,
        })

        try:
            result = await run_case_with_watchdog(
                executor.retrieve(
                    q,
                    user_id=7001,
                    top_k=TOP_K,
                    max_rounds=max(1, decision.max_retrieval_rounds),
                    enable_query_rewrite=decision.enable_query_rewrite,
                    enable_multi_query=decision.enable_multi_query,
                    enable_decomposition=decision.enable_decomposition,
                ),
                run_index=run_index,
                case=case,
                ledger=ledger,
            )
            latency = (time.perf_counter() - started) * 1000
            new_fallbacks = fallback[fallback_before:]
            if new_fallbacks:
                raise RuntimeError(f"forbidden model fallback: {new_fallbacks[-1]}")
            hits = result.hits
            if any((hit.document.metadata.get("ragDiagnostics") or {}).get("rerankFallback") for hit in hits):
                raise RuntimeError(f"forbidden reranker fallback case={case['case_id']}")

            calls = model.calls[before_model_calls:]
            diagnostics = [hit.document.metadata.get("ragDiagnostics") or {} for hit in hits]
            delta = ledger.delta(before_ledger)
            row = {
                **{key: case[key] for key in ["case_id", "category", "answerable", "gold_chunk_ids"]},
                "query": case["query"],
                "route": decision.mode.value,
                "retrieved_chunk_ids": [hit.document.id for hit in hits],
                "hits": [
                    {"chunk_id": hit.document.id, "rank": rank, "score": hit.score}
                    for rank, hit in enumerate(hits, 1)
                ],
                "evidence_sufficient": result.sufficient,
                "rounds": len(result.rounds),
                "latency_ms": latency,
                **delta,
                "stage_latency_ms": {
                    "rewrite": sum(call["latency_ms"] for call in calls if call["kind"] != "evidence_grading"),
                    "evidence_grading": sum(call["latency_ms"] for call in calls if call["kind"] == "evidence_grading"),
                    "retrieval": sum(float(item.get("hybridSearchMs", 0)) for item in diagnostics),
                    "rerank": sum(float(item.get("rerankMs", 0)) for item in diagnostics),
                },
            }
            row["metrics"] = row_metrics(row)
            rows.append(row)
            _write_checkpoint(
                artifact_name,
                fingerprint=fingerprint,
                rows=rows,
                status="IN_PROGRESS",
            )
            emit({
                "stage": stage_name,
                "event": "case_end",
                "index": index,
                "total": len(cases),
                "case_id": case["case_id"],
                "category": case["category"],
                "latency_ms": round(latency, 2),
                "retry_count": row["retry_count"],
            })
            if index % 10 == 0:
                emit({"stage": stage_name, "completed": index, "total": len(cases)})
        except Exception as exc:
            failure = {
                "case_id": case["case_id"],
                "category": case["category"],
                "exception": type(exc).__name__,
                "error": str(exc)[:1000],
                "last_external_stage": ledger.current_stage or None,
            }
            _write_checkpoint(
                artifact_name,
                fingerprint=fingerprint,
                rows=rows,
                status="BLOCKED",
                failure=failure,
            )
            emit({
                "stage": stage_name,
                "event": "case_blocked",
                "index": index,
                "case_id": case["case_id"],
                "category": case["category"],
                **failure,
                "checkpoint": str(_checkpoint_path(artifact_name)),
            })
            raise

    metrics = aggregate(rows)
    for stage in ["rewrite", "retrieval", "rerank", "evidence_grading"]:
        vals = [row["stage_latency_ms"][stage] for row in rows]
        metrics.setdefault("stage_latency_ms", {})[stage] = {
            "p50": pct(vals, 0.5),
            "p95": pct(vals, 0.95),
        }
    metrics["end_to_end_latency_ms"] = metrics.pop("latency_ms")
    output = {
        "status": "PASS",
        "pipeline": "PRODUCTION_FULL",
        "run": run_index,
        "completed": len(rows),
        "top_k": TOP_K,
        "rows": rows,
        "metrics": metrics,
        "retry_statistics": aggregate_retry_statistics(rows),
        "fallback": False,
        "fingerprint": fingerprint,
        "case_timeout_seconds": CASE_TIMEOUT_SECONDS,
    }
    dump(artifact_name, output)
    _write_checkpoint(
        artifact_name,
        fingerprint=fingerprint,
        rows=rows,
        status="COMPLETED",
    )
    return output


def finalize(validation, collection, base, runs):
    mean = {}
    keys = [
        "recall_at_5",
        "recall_at_10",
        "hit_at_5",
        "mrr_at_10",
        "ndcg_at_10",
        "negative_evidence_error_rate",
    ]
    for key in keys:
        vals = [run["metrics"][key] for run in runs]
        mean[key] = {"mean": statistics.fmean(vals), "min": min(vals), "max": max(vals)}
    full_rows = runs[0]["rows"]
    baseline_map = {row["case_id"]: row for row in base["rows"]}
    full_map = {row["case_id"]: row for row in full_rows}
    improved = []
    regressed = []
    misses = []
    for case_id, baseline_row in baseline_map.items():
        if not baseline_row["answerable"]:
            continue
        baseline_hit = baseline_row["metrics"]["hit_at_5"] > 0
        full_hit = full_map[case_id]["metrics"]["hit_at_5"] > 0
        if not baseline_hit and full_hit:
            improved.append(case_id)
        if baseline_hit and not full_hit:
            regressed.append(case_id)
        if not full_hit:
            category = full_map[case_id]["category"]
            reason = (
                "multi-evidence incomplete"
                if category == "multi_evidence"
                else ("reference resolution" if category == "multi_turn_reference" else "other")
            )
            misses.append({"case_id": case_id, "reason": reason})
    analysis = {
        "baseline_miss_to_full_hit": improved,
        "baseline_hit_to_full_miss": regressed,
        "full_misses": misses,
        "reason_distribution": dict(Counter(item["reason"] for item in misses)),
    }
    dump("failure_analysis.json", analysis)
    report = {
        "status": "PASS",
        "validation": validation,
        "collection": collection,
        "baseline": base["metrics"],
        "production_runs": [run["metrics"] for run in runs],
        "production_aggregate": mean,
        "failure_analysis": analysis,
        "fallback": False,
        "top_k": TOP_K,
    }
    dump("report.json", report)
    baseline = base["metrics"]
    full = {key: mean[key]["mean"] for key in keys}
    categories = []
    for category, value in baseline["by_category"].items():
        categories.append(
            f"| {category} | {value['recall_at_5']:.4f} | "
            f"{statistics.fmean(run['metrics']['by_category'][category]['recall_at_5'] for run in runs):.4f} |"
        )
    (HERE / "report.md").write_text(
        f"""# AgentMesh Final Real-Model RAG Evaluation

Status: **PASS**

Corpus: 30 documents / 210 chunks (`{EXPECTED_CORPUS}`)  
Benchmark: 100 answerable + 20 negative (`{EXPECTED_BENCH}`)  
Collection: `{collection['collection']}`; TopK: {TOP_K}; fallback: NO

| Pipeline | Recall@5 | Recall@10 | Hit@5 | MRR@10 | nDCG@10 | Negative Error |
|---|---:|---:|---:|---:|---:|---:|
| Vector Baseline | {baseline['recall_at_5']:.4f} | {baseline['recall_at_10']:.4f} | {baseline['hit_at_5']:.4f} | {baseline['mrr_at_10']:.4f} | {baseline['ndcg_at_10']:.4f} | N/A |
"""
        + "".join(
            f"| Production Full run {i + 1} | {run['metrics']['recall_at_5']:.4f} | {run['metrics']['recall_at_10']:.4f} | {run['metrics']['hit_at_5']:.4f} | {run['metrics']['mrr_at_10']:.4f} | {run['metrics']['ndcg_at_10']:.4f} | {run['metrics']['negative_evidence_error_rate']:.4f} |\n"
            for i, run in enumerate(runs)
        )
        + f"""

Recall@5 change: {baseline['recall_at_5']:.1%} → {full['recall_at_5']:.1%} ({(full['recall_at_5'] - baseline['recall_at_5']) * 100:+.1f} percentage points).

## Category Recall@5

| Category | Baseline | Full mean |
|---|---:|---:|
{chr(10).join(categories)}

Baseline MISS → Full HIT: {len(improved)}  
Baseline HIT → Full MISS: {len(regressed)}  
Full misses: {len(misses)}
""",
        encoding="utf-8",
    )
    return report


def parse_args(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(
        description="Strict-real AgentMesh frozen RAG evaluation with liveness guards."
    )
    parser.add_argument(
        "--smoke-boundary",
        action="store_true",
        help="Run only the multi-evidence → multi-turn boundary cases once; do not produce formal 120x3 metrics.",
    )
    parser.add_argument(
        "--case-id",
        action="append",
        default=[],
        help="Run one or more selected benchmark case IDs once as a non-formal smoke run.",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Ignore compatible checkpoints and start the selected run from its first case.",
    )
    return parser.parse_args(argv)


async def main(argv: list[str] | None = None):
    args = parse_args(argv)
    validation = validate()
    manifest, cases = load()
    from app.config import settings

    if (
        settings.embedding_backend != "openai_compatible"
        or settings.model_provider != "openai_compatible"
        or settings.reranker_backend != "qwen"
    ):
        raise RuntimeError("strict-real configuration mismatch")

    from app.rag.embedding import OpenAICompatibleEmbeddingProvider
    from app.models.providers import OpenAICompatibleModelProvider
    from app.models.gateway import ModelGateway

    ledger = RetryLedger()
    real_embedding = OpenAICompatibleEmbeddingProvider(
        api_key=settings.embedding_api_key,
        base_url=settings.embedding_base_url,
        model=settings.embedding_model,
        dimension=256,
        trust_env=settings.embedding_http_trust_env,
        timeout_seconds=EMBEDDING_TIMEOUT_SECONDS,
        sdk_max_retries=0,
    )
    embedding = RetryEmbedding(real_embedding, ledger)
    client = hybrid = None
    try:
        client, hybrid, collection = await build_collection(manifest, embedding, settings)
        emit({"stage": "collection", "status": "PASS", **collection})
        baseline_path = HERE / "vector_baseline_results.json"
        if baseline_path.exists():
            candidate = json.loads(baseline_path.read_text(encoding="utf-8"))
            base = (
                candidate
                if candidate.get("status") == "PASS"
                and candidate.get("top_k") == TOP_K
                and len(candidate.get("rows", [])) == 120
                else await baseline(cases, settings, embedding, client)
            )
            if base is candidate:
                emit({"stage": "baseline", "status": "PASS", "reused": True, "cases": 120})
        else:
            base = await baseline(cases, settings, embedding, client)

        provider = OpenAICompatibleModelProvider(
            api_key=settings.model_api_key,
            base_url=settings.model_base_url,
            trust_env=settings.model_http_trust_env,
        )
        model = TimedModel(
            ModelGateway(provider, timeout=settings.model_timeout_seconds, max_retries=0),
            settings.model_name,
            ledger,
        )
        from app.rag.reranker import QwenReranker

        await hybrid.reranker.aclose()
        hybrid.reranker = RetryReranker(
            QwenReranker(
                api_key=settings.reranker_api_key,
                base_url=settings.reranker_base_url,
                model=settings.reranker_model,
                timeout_seconds=settings.reranker_timeout_seconds,
                trust_env=settings.reranker_http_trust_env,
                instruct=settings.reranker_instruct,
            ),
            ledger,
        )

        if args.smoke_boundary or args.case_id:
            selected_ids = set(args.case_id or SMOKE_BOUNDARY_CASE_IDS)
            selected = [case for case in cases if case["case_id"] in selected_ids]
            missing = selected_ids - {case["case_id"] for case in selected}
            if missing:
                raise RuntimeError(f"unknown benchmark case IDs: {sorted(missing)}")
            result = await full_run(
                0,
                selected,
                settings,
                hybrid,
                model,
                ledger,
                artifact_name="smoke_boundary_result.json",
                allow_resume=False,
                stage_name="smoke_boundary",
            )
            emit({
                "stage": "smoke_boundary",
                "status": "PASS",
                "completed": result["completed"],
                "case_ids": [case["case_id"] for case in selected],
            })
            return 0

        runs = []
        for run_index in range(1, 4):
            runs.append(
                await full_run(
                    run_index,
                    cases,
                    settings,
                    hybrid,
                    model,
                    ledger,
                    allow_resume=not args.no_resume,
                )
            )
        finalize(validation, collection, base, runs)
    finally:
        if hybrid is not None:
            await hybrid.aclose()
        elif embedding is not None:
            await embedding.aclose()
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
