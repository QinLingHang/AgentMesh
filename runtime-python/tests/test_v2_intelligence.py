from __future__ import annotations

import json

import pytest

from app.eval.dataset import (
    EvaluationCase,
    compare_evaluation_runs,
    run_evaluation_dataset,
)
from app.eval.judge import DeterministicMockJudge, _safe_eval_value
from app.models.cost import ModelPricing, UsageCostCalculator
from app.multimodal.contracts import RetrievalMode, VisionObservation, VisualType
from app.multimodal.ingestion import ingest_multimodal_document
from app.multimodal.retrieval import (
    classify_retrieval_mode,
    diversify_multimodal_hits,
    filter_hits_for_mode,
)
from app.multimodal.vision import DeterministicVisionAnalyzer
from app.rag.provenance import build_evidence_provenance
from app.rag.query_intelligence import QueryAnalyzer
from app.rag.runtime import RetrievalDocument, RetrievalHit
from app.schemas import AgentFeedback, DynamicDAG, RuntimeCitation, TraceEvent
from app.services.citation_projection import project_used_citations
from app.services.observability import build_observability_summary


def hit(identity: str, modality: str, score: float, *, page: int | None = None) -> RetrievalHit:
    metadata = {"documentId": "doc-1", "modality": modality}
    if page is not None:
        metadata["pageNumber"] = page
    return RetrievalHit(
        document=RetrievalDocument(id=identity, text=f"{modality} evidence", source="demo.pdf", metadata=metadata),
        score=score,
    )


def test_retrieval_mode_combines_multimodal_signals_with_existing_query_intelligence() -> None:
    analyzer = QueryAnalyzer()

    text = classify_retrieval_mode("解释这份文档正文中的 Memory 机制", analyzer.analyze("解释这份文档正文中的 Memory 机制"))
    visual = classify_retrieval_mode("图 3 中 Worker 与 Dispatcher 是什么关系", analyzer.analyze("图 3 中 Worker 与 Dispatcher 是什么关系"))
    hybrid = classify_retrieval_mode("结合正文和图表解释系统性能", analyzer.analyze("结合正文和图表解释系统性能"))

    assert text.mode is RetrievalMode.TEXT
    assert visual.mode is RetrievalMode.VISUAL
    assert hybrid.mode is RetrievalMode.HYBRID
    assert "intent=" in hybrid.reason

    # The Chinese character "图" can be part of an ordinary text concept.
    # It must not turn text questions such as "图数据库" into visual retrieval.
    graph_db = classify_retrieval_mode(
        "解释图数据库的索引机制",
        analyzer.analyze("解释图数据库的索引机制"),
    )
    visual_relation = classify_retrieval_mode(
        "这张图中 Worker 与 Dispatcher 是什么关系",
        analyzer.analyze("这张图中 Worker 与 Dispatcher 是什么关系"),
    )
    assert graph_db.mode is RetrievalMode.TEXT
    assert visual_relation.mode is RetrievalMode.VISUAL


@pytest.mark.asyncio
async def test_image_ingestion_creates_searchable_visual_evidence() -> None:
    observation = VisionObservation(
        summary="Worker A and Worker B are connected to a dispatcher.",
        visual_type=VisualType.ARCHITECTURE.value,
        visible_text=("Dispatcher", "Worker A", "Worker B"),
        relationships=("Dispatcher dispatches jobs to workers",),
    )
    analyzer = DeterministicVisionAnalyzer({"architecture.png": observation})

    result = await ingest_multimodal_document(
        content=b"synthetic-image-bytes",
        extension="png",
        source="architecture.png",
        base_metadata={
            "userId": 7,
            "knowledgeBaseId": 9,
            "knowledgeFileId": 11,
            "documentId": "knowledge-file-11",
            "documentType": "png",
            "checksumSha256": "0" * 64,
            "projectId": 13,
        },
        vision_analyzer=analyzer,
    )

    assert result.stats.visual_evidence == 1
    assert result.stats.text_chunks == 0
    assert result.stats.visual_status == "completed"
    assert result.documents[0].metadata["modality"] == "image"
    assert result.documents[0].metadata["visualType"] == "architecture"
    assert "Dispatcher" in result.documents[0].text


@pytest.mark.asyncio
async def test_pdf_visual_failure_preserves_text_layer(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.multimodal import ingestion as module

    monkeypatch.setattr(module, "_page_texts", lambda _: ["AgentMesh runtime text layer."])

    def fail_render(*_args, **_kwargs):
        raise RuntimeError("synthetic renderer unavailable")

    monkeypatch.setattr(module, "_render_pdf_pages", fail_render)

    result = await ingest_multimodal_document(
        content=b"synthetic-pdf",
        extension="pdf",
        source="guide.pdf",
        base_metadata={
            "userId": 1,
            "knowledgeBaseId": 2,
            "knowledgeFileId": 3,
            "documentId": "knowledge-file-3",
            "documentType": "pdf",
            "checksumSha256": "1" * 64,
        },
        vision_analyzer=DeterministicVisionAnalyzer(),
    )

    assert result.stats.text_chunks > 0
    assert result.stats.visual_evidence == 0
    assert result.stats.visual_status == "failed"
    assert "renderer unavailable" in result.stats.visual_error
    assert any(item.metadata["modality"] == "text" for item in result.documents)


def test_visual_and_hybrid_retrieval_filters_and_diversifies() -> None:
    hits = [
        hit("text-1", "text", 0.99, page=1),
        hit("page-1a", "page", 0.95, page=2),
        hit("page-1b", "page", 0.94, page=2),
        hit("image-1", "image", 0.91, page=3),
    ]

    visual = filter_hits_for_mode(hits, RetrievalMode.VISUAL)
    hybrid = filter_hits_for_mode(hits, RetrievalMode.HYBRID)
    diversified = diversify_multimodal_hits(visual, top_k=5)

    assert [item.document.metadata["modality"] for item in visual] == ["page", "page", "image"]
    assert len(hybrid) == 4
    assert [item.document.id for item in diversified] == ["page-1a", "image-1"]


def test_multimodal_provenance_projects_page_asset_and_modality() -> None:
    selected = RetrievalHit(
        document=RetrievalDocument(
            id="visual-7",
            text="architecture evidence",
            source="architecture.pdf",
            metadata={
                "documentType": "pdf",
                "pageNumber": 6,
                "assetId": "asset-page-6",
                "modality": "page",
                "visualType": "architecture",
                "userId": 99,
            },
        ),
        score=0.93,
    )
    provenance = build_evidence_provenance([selected])
    citations = project_used_citations(provenance=provenance, used_citation_ids=[1])

    assert citations == [
        RuntimeCitation(
            citationId=1,
            label="[1]",
            documentId="visual-7",
            source="architecture.pdf",
            score=0.93,
            documentType="pdf",
            chunkIndex=None,
            start=None,
            end=None,
            pageNumber=6,
            assetId="asset-page-6",
            modality="page",
            visualType="architecture",
        )
    ]
    assert "userId" not in provenance[0].metadata
    assert "visibleText" not in provenance[0].metadata
    assert "visionMetadata" not in provenance[0].metadata


@pytest.mark.asyncio
async def test_deterministic_judge_dataset_and_regression_comparison() -> None:
    judge = DeterministicMockJudge()
    baseline = await run_evaluation_dataset(
        [EvaluationCase(case_id="c1", task="Explain", actual_answer="short", reference_answer="target answer")],
        judge,
    )
    candidate = await run_evaluation_dataset(
        [EvaluationCase(case_id="c1", task="Explain", actual_answer="target answer", reference_answer="target answer")],
        judge,
    )
    comparison = compare_evaluation_runs(baseline, candidate, improvement_threshold=0.01)

    assert baseline.total == 1
    assert candidate.total == 1
    assert candidate.mean_score >= baseline.mean_score
    assert comparison.mean_delta >= 0
    assert len(comparison.improvements) == 1


def test_usage_cost_calculator_distinguishes_estimated_and_unavailable() -> None:
    known = UsageCostCalculator.calculate(
        input_tokens=1_000_000,
        output_tokens=500_000,
        pricing=ModelPricing(input_cost_per_million=1.0, output_cost_per_million=2.0),
    )
    unknown = UsageCostCalculator.calculate(
        input_tokens=100,
        output_tokens=100,
        pricing=ModelPricing(),
    )

    assert known.status == "estimated"
    assert known.amount == 2.0
    assert unknown.status == "unavailable"
    assert unknown.amount is None


def test_observability_collects_multimodal_rag_model_and_cost_metrics() -> None:
    trace = [
        TraceEvent(kind="model", title="Model Call Completed", status="completed", elapsedMs=15, detail=json.dumps({
            "provider": "mock", "model": "mock-v2", "input_tokens": 10, "output_tokens": 5,
            "total_tokens": 15, "latency_ms": 12, "estimated_cost": 0.01, "cost_known": True,
        })),
        TraceEvent(kind="rag", title="RAG Retrieval Started", status="running", elapsedMs=20, detail=json.dumps({"retrievalMode": "hybrid"})),
        TraceEvent(kind="rag", title="RAG Retrieval Completed", status="completed", elapsedMs=37, detail=json.dumps({
            "retrievalMode": "hybrid", "rawHits": 8, "hits": 4, "contextHits": 3,
            "textCandidates": 5, "visualCandidates": 3,
        })),
    ]
    summary = build_observability_summary(trace=trace, feedback=[], dag=DynamicDAG(nodes=[], edges=[]))

    assert summary.model_provider == "mock"
    assert summary.model_name == "mock-v2"
    assert summary.model_total_tokens == 15
    assert summary.model_cost_known is True
    assert summary.retrieval_mode == "hybrid"
    assert summary.rag_latency_ms == 17
    assert summary.rag_text_candidates == 5
    assert summary.rag_visual_candidates == 3


def test_v2_regression_dataset_covers_required_synthetic_scenarios() -> None:
    from pathlib import Path

    from app.eval.dataset import load_jsonl_dataset

    path = Path(__file__).resolve().parents[1] / "evals" / "v2_intelligence_cases.jsonl"
    cases = load_jsonl_dataset(path)
    tags = {tag for case in cases for tag in case.tags}
    required = {
        "text_only_rag",
        "image_knowledge",
        "pdf_text",
        "pdf_visual",
        "visual_query",
        "hybrid_query",
        "citation",
        "memory_interaction",
        "tool_interaction",
        "routing",
        "failure_fallback",
    }

    assert len(cases) >= len(required)
    assert required <= tags
    assert all(case.metadata == {} for case in cases)
    citation_case = next(case for case in cases if case.case_id == "v2-citation-001")
    tool_case = next(case for case in cases if case.case_id == "v2-tool-interaction-001")
    assert citation_case.citations[0].page_number == 2
    assert citation_case.citations[0].modality == "text"
    assert tool_case.tool_trace[0]["tool"] == "calculator"


@pytest.mark.asyncio
async def test_pdf_visual_limit_is_reported_as_partial(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.multimodal import ingestion as module

    monkeypatch.setattr(module, "_page_texts", lambda _: ["page one", "page two", "page three"])
    monkeypatch.setattr(module, "_render_pdf_pages", lambda *_args, **_kwargs: [(1, b"p1"), (2, b"p2")])

    result = await ingest_multimodal_document(
        content=b"synthetic-pdf",
        extension="pdf",
        source="large.pdf",
        base_metadata={
            "userId": 1,
            "knowledgeBaseId": 2,
            "knowledgeFileId": 4,
            "documentId": "knowledge-file-4",
            "documentType": "pdf",
            "checksumSha256": "4" * 64,
        },
        vision_analyzer=DeterministicVisionAnalyzer(),
        max_visual_pages=2,
    )

    assert result.stats.page_count == 3
    assert result.stats.visual_evidence == 2
    assert result.stats.visual_status == "partial"


@pytest.mark.asyncio
async def test_real_vision_analyzer_refuses_text_only_runtime() -> None:
    from types import SimpleNamespace

    from app.multimodal.vision import ModelVisionAnalyzer

    class Gateway:
        async def generate(self, _request):  # pragma: no cover - must never be reached
            raise AssertionError("text-only runtime must not receive image payload")

    runtime = SimpleNamespace(
        provider="openai_compatible",
        model="text-only-model",
        vision_model=None,
        gateway=Gateway(),
    )

    with pytest.raises(RuntimeError, match="vision-capable model is not configured"):
        await ModelVisionAnalyzer(runtime).analyze_image(
            content=b"fixture",
            media_type="image/png",
            source_name="fixture.png",
        )


def test_visual_failure_message_redacts_secret_material() -> None:
    from app.multimodal.ingestion import _safe_visual_error

    error = RuntimeError(
        "provider failed api_key=sk-test-secret Authorization: Bearer abc.def.ghi password=hunter2"
    )
    safe = _safe_visual_error(error)

    assert "sk-test-secret" not in safe
    assert "abc.def.ghi" not in safe
    assert "hunter2" not in safe
    assert "[redacted]" in safe

@pytest.mark.asyncio
async def test_knowledge_indexer_prefers_request_local_vision_analyzer() -> None:
    from app.knowledge.indexer import KnowledgeIndexInput, KnowledgeIndexer

    class Backend:
        def __init__(self) -> None:
            self.saved = []

        def add_documents(self, documents) -> None:
            self.saved.extend(documents)

    default = DeterministicVisionAnalyzer({
        "tenant.png": VisionObservation(summary="default platform observation")
    })
    tenant = DeterministicVisionAnalyzer({
        "tenant.png": VisionObservation(summary="request-local tenant observation")
    })
    backend = Backend()
    indexer = KnowledgeIndexer(backend, vision_analyzer=default)

    result = await indexer.index_detailed(
        KnowledgeIndexInput(
            user_id=1,
            knowledge_base_id=2,
            knowledge_file_id=3,
            project_id=4,
            original_name="tenant.png",
            extension="png",
            checksum_sha256="f" * 64,
        ),
        b"synthetic-image",
        vision_analyzer_override=tenant,
    )

    assert result.stats.visual_evidence == 1
    assert len(backend.saved) == 1
    assert "request-local tenant observation" in backend.saved[0].text
    assert "default platform observation" not in backend.saved[0].text


def test_request_local_model_runtime_requires_explicit_vision_for_knowledge() -> None:
    from app.models.runtime import resolve_project_model_runtime
    from app.schemas import ProjectModelRuntime

    configured = ProjectModelRuntime.model_validate({
        "provider": "openai-compatible",
        "baseUrl": "https://api.example.test/v1",
        "modelName": "text-or-multimodal-model",
        "apiKey": "sk-synthetic-v2-only",
    })

    # Normal P9 task execution remains backward compatible: a provider may expose
    # one multimodal model through modelName. Knowledge ingestion is stricter and
    # requires an explicit visionModelName before it sends image bytes.
    normal = resolve_project_model_runtime(configured)
    strict = resolve_project_model_runtime(configured, require_explicit_vision=True)

    assert normal.vision_model == "text-or-multimodal-model"
    assert strict.vision_model is None


@pytest.mark.asyncio
async def test_image_ingestion_provider_failure_is_secret_redacted() -> None:
    class FailingAnalyzer:
        async def analyze_image(self, **_kwargs):
            raise RuntimeError(
                "provider rejected api_key=sk-image-secret Authorization: Bearer abc.def.ghi password=hunter2"
            )

    with pytest.raises(RuntimeError) as captured:
        await ingest_multimodal_document(
            content=b"synthetic-image",
            extension="png",
            source="private.png",
            base_metadata={
                "userId": 1,
                "knowledgeBaseId": 2,
                "knowledgeFileId": 5,
                "documentId": "knowledge-file-5",
                "documentType": "png",
                "checksumSha256": "5" * 64,
            },
            vision_analyzer=FailingAnalyzer(),
        )

    message = str(captured.value)
    assert "sk-image-secret" not in message
    assert "abc.def.ghi" not in message
    assert "hunter2" not in message
    assert "[redacted]" in message


def test_model_judge_redacts_secret_like_tool_trace_values() -> None:
    sanitized = _safe_eval_value({
        "tool": "http",
        "apiKey": "sk-test-secret",
        "nested": {"authorization": "Bearer abc.def.ghi", "result": "ok"},
    })
    assert sanitized["apiKey"] == "[REDACTED]"
    assert sanitized["nested"]["authorization"] == "[REDACTED]"
    assert sanitized["nested"]["result"] == "ok"


@pytest.mark.asyncio
async def test_v2_regression_dataset_is_offline_safe_and_passes_deterministic_baseline() -> None:
    from pathlib import Path

    from app.eval.dataset import load_jsonl_dataset

    path = Path(__file__).resolve().parents[1] / "evals" / "v2_intelligence_cases.jsonl"
    cases = load_jsonl_dataset(path)
    result = await run_evaluation_dataset(cases, DeterministicMockJudge())

    assert result.total == len(cases) == 11
    assert result.passed == result.total
    assert result.failed == 0
    assert result.mean_score >= 0.70
    citation_result = next(item for item in result.cases if item.case_id == "v2-citation-001")
    assert citation_result.judge.dimension_scores["citation_quality"] == pytest.approx(0.92)


def test_v2_eval_direct_script_entrypoint_bootstraps_runtime_root() -> None:
    import subprocess
    import sys
    from pathlib import Path

    runtime_root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, "scripts/run_v2_eval.py"],
        cwd=runtime_root,
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
    payload = json.loads(completed.stdout)
    assert payload["total"] == 11
    assert payload["passed"] == 11
    assert payload["failed"] == 0
