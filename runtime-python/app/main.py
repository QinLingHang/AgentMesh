from contextlib import asynccontextmanager
import asyncio
import json

from fastapi import (
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    UploadFile,
)
from pydantic import BaseModel, Field, ValidationError
from fastapi.responses import StreamingResponse

from app.config import settings
from app.distributed import (
    DurableExecutionEnvelope,
    DurableExecutionManager,
    WorkerUnavailable,
    build_result_transport,
)
from app.knowledge import (
    KnowledgeIndexer,
    KnowledgeScope,
    KnowledgeScopeClient,
    install_scoped_retriever,
    reset_candidate_knowledge_ids,
    reset_knowledge_scope,
    set_candidate_knowledge_ids,
    set_knowledge_scope,
)
from app.knowledge.indexer import KnowledgeIndexInput
from app.mcp import MCPDiscoverRequest, MCPManager
from app.multimodal.ingestion import safe_knowledge_error
from app.multimodal.vision import DeterministicVisionAnalyzer, ModelVisionAnalyzer
from app.models.runtime import resolve_project_model_runtime
from app.schemas import InteractiveStreamRequest, ProjectModelRuntime, RuntimeRequest, RuntimeResponse, TraceEvent
from app.services import RuntimeEngine, create_registry
from app.services.interactive_stream import encode_ndjson, stream_interactive_answer
from app.semantics.intent_understanding import TaskUnderstandingRequest, TaskUnderstandingResult, understand

registry = None
engine = None
knowledge_indexer: KnowledgeIndexer | None = None
knowledge_scope_client: KnowledgeScopeClient | None = None
execution_manager: DurableExecutionManager | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global registry, engine, knowledge_indexer, knowledge_scope_client, execution_manager

    registry = await create_registry()
    engine = RuntimeEngine(registry)

    # Keep the concrete Milvus/Hybrid retriever for ingestion.
    # Runtime retrieval is wrapped with request-local KnowledgeBase scope.
    base_retriever, _ = install_scoped_retriever(engine)
    default_model_runtime = registry.context.get("model.runtime.default")
    default_provider = str(getattr(default_model_runtime, "provider", "")).strip().lower()
    configured_vision_model = str(getattr(default_model_runtime, "vision_model", "") or "").strip()
    if default_provider == "mock":
        vision_analyzer = DeterministicVisionAnalyzer()
    elif default_model_runtime is not None and configured_vision_model:
        vision_analyzer = ModelVisionAnalyzer(default_model_runtime)
    else:
        # Text knowledge remains fully available when the deployment has no
        # vision-capable model configured. Image-only knowledge will fail with
        # an explicit ingestion error instead of being sent to a text-only model.
        vision_analyzer = None
    knowledge_indexer = KnowledgeIndexer(base_retriever, vision_analyzer=vision_analyzer)
    knowledge_scope_client = KnowledgeScopeClient(
        internal_token=settings.internal_token,
    )

    if settings.runtime_worker_enabled:
        result_transport = build_result_transport(
            mode=settings.runtime_result_transport,
            internal_token=settings.internal_token,
            callback_timeout_seconds=settings.runtime_worker_callback_timeout_seconds,
            callback_max_retries=settings.runtime_worker_callback_max_retries,
            kafka_brokers=settings.kafka_brokers,
            kafka_topic=settings.kafka_runtime_result_topic,
            kafka_client_id=settings.kafka_client_id,
            kafka_outbox_path=settings.kafka_outbox_path,
            kafka_publish_timeout_seconds=settings.kafka_publish_timeout_seconds,
        )
        execution_manager = DurableExecutionManager(
            worker_id=settings.runtime_worker_id,
            worker_endpoint=settings.runtime_worker_endpoint,
            capacity=settings.runtime_worker_capacity,
            internal_token=settings.internal_token,
            control_plane_base_url=settings.control_plane_internal_base_url,
            heartbeat_interval_seconds=settings.runtime_worker_heartbeat_seconds,
            callback_timeout_seconds=settings.runtime_worker_callback_timeout_seconds,
            callback_max_retries=settings.runtime_worker_callback_max_retries,
            shutdown_grace_seconds=settings.runtime_worker_shutdown_grace_seconds,
            dedupe_retention_seconds=settings.runtime_worker_dedupe_retention_seconds,
            runner=run_scoped_runtime,
            event_runner=run_scoped_runtime,
            node_id=settings.runtime_node_id or settings.runtime_worker_id,
            node_zone=settings.runtime_node_zone,
            node_version=settings.runtime_node_version,
            node_capacity=settings.runtime_node_capacity or settings.runtime_worker_capacity,
            result_transport=result_transport,
        )
        await execution_manager.start()

    yield

    if execution_manager is not None:
        await execution_manager.stop()
        execution_manager = None

    await registry.stop_all()


app = FastAPI(
    title="AgentMesh Runtime",
    version="0.4.0-p1-knowledge",
    lifespan=lifespan,
)


def verify_internal(x_internal_token: str) -> None:
    if x_internal_token != settings.internal_token:
        raise HTTPException(
            status_code=401,
            detail="invalid internal token",
        )


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "agentmesh-runtime",
        "provider": settings.model_provider,
        "model": settings.model_name,
        "workerEnabled": settings.runtime_worker_enabled,
        "workerId": settings.runtime_worker_id if settings.runtime_worker_enabled else None,
        "nodeId": execution_manager.node_id if execution_manager is not None else None,
        "nodeZone": execution_manager.node_zone if execution_manager is not None else None,
        "nodeVersion": execution_manager.node_version if execution_manager is not None else None,
        "workerCapacity": execution_manager.capacity if execution_manager is not None else 0,
        "nodeCapacity": execution_manager.node_capacity if execution_manager is not None else 0,
        "draining": execution_manager.draining if execution_manager is not None else False,
        "activeExecutions": execution_manager.active_count() if execution_manager is not None else 0,
        "heartbeat": execution_manager.heartbeat_status() if execution_manager is not None else None,
        "resultTransport": execution_manager.result_transport_status() if execution_manager is not None else None,
    }


@app.get("/livez")
async def livez():
    """Process liveness only; external dependencies are intentionally ignored."""
    return {
        "status": "alive",
        "service": "agentmesh-runtime",
    }


@app.get("/readyz")
async def readyz():
    """Traffic-admission readiness for the request-local runtime plane."""
    checks = {
        "registry": registry is not None,
        "engine": engine is not None,
        "knowledgeScope": knowledge_scope_client is not None,
    }

    if settings.runtime_worker_enabled:
        checks["worker"] = execution_manager is not None
        checks["accepting"] = (
            execution_manager is not None
            and not execution_manager.draining
        )

    if not all(checks.values()):
        raise HTTPException(
            status_code=503,
            detail={
                "status": "not_ready",
                "service": "agentmesh-runtime",
                "checks": checks,
            },
        )

    return {
        "status": "ready",
        "service": "agentmesh-runtime",
        "checks": checks,
    }


@app.get("/internal/v1/runtime/plugins")
async def plugins(
    x_internal_token: str = Header(default=""),
):
    verify_internal(x_internal_token)
    if registry is None:
        raise HTTPException(status_code=503, detail="runtime not ready")
    return registry.info()


async def resolve_request_scope(req: RuntimeRequest) -> KnowledgeScope:
    # RAG V1.1: Go Control Plane may send an already-authorized effective
    # policy snapshot. Runtime must never widen that set. This also removes
    # the historical behaviour where a non-project conversation implicitly
    # gained access to every user-global knowledge base.
    policy = req.effective_rag_policy
    if policy is not None:
        project_id = None
        for item in req.knowledge_catalog:
            if item.scope == "PROJECT" and item.project_id is not None:
                project_id = item.project_id
                break
        return KnowledgeScope(
            user_id=req.user_id,
            conversation_id=req.conversation_id,
            project_id=project_id,
            mode="POLICY",
            knowledge_base_ids=tuple(
                int(value)
                for value in policy.allowed_knowledge_base_ids
                if int(value) > 0
            ),
            live_authorizer=(knowledge_scope_client.authorize if knowledge_scope_client is not None else None),
            require_live_authorization=True,
        )

    if knowledge_scope_client is None:
        raise HTTPException(status_code=503, detail="knowledge scope client not ready")

    try:
        return await knowledge_scope_client.resolve(
            user_id=req.user_id,
            conversation_id=req.conversation_id,
        )
    except Exception:
        # Security boundary: public Runtime execution must never silently fall
        # back to userId-only retrieval when the Control Plane scope cannot be
        # resolved. Fail closed with an empty explicit scope.
        return KnowledgeScope(
            user_id=req.user_id,
            conversation_id=req.conversation_id,
            project_id=None,
            mode="UNRESOLVED",
            knowledge_base_ids=(),
        )


async def run_scoped_runtime(req: RuntimeRequest, event_sink=None, delta_sink=None) -> RuntimeResponse:
    if engine is None:
        raise HTTPException(status_code=503, detail="runtime not ready")

    scope = await resolve_request_scope(req)
    token = set_knowledge_scope(scope)
    candidate_token = set_candidate_knowledge_ids(None)
    try:
        response = await engine.run(req, event_sink=event_sink, delta_sink=delta_sink)
        # P23 metadata comes only from the internal Go-signed execution request.
        # Persist the same privacy-safe decision trace for direct and durable
        # runs, including the no-DAG Knowledge executor, without re-routing.
        if req.p23_strategy in {"SINGLE_CAPABILITY", "WORKFLOW", "RUNTIME"}:
            response.trace.insert(0, TraceEvent(**{
                "kind": "routing", "title": "P23 Execution Decision",
                "status": "completed", "elapsedMs": 0,
                "detail": json.dumps({
                    "decisionVersion": "p23.v2" if req.p23_strategy == "RUNTIME" else "p23.v1", "strategy": req.p23_strategy,
                    "capabilityKind": req.p23_capability_kind,
                }, ensure_ascii=False),
            }))
        return response
    finally:
        reset_candidate_knowledge_ids(candidate_token)
        reset_knowledge_scope(token)


@app.post("/internal/v1/p23/understand", response_model=TaskUnderstandingResult)
async def p23_understand(
    req: TaskUnderstandingRequest,
    x_internal_token: str = Header(default=""),
):
    """Trusted, read-only preflight. A suggestion is never execution permission."""
    verify_internal(x_internal_token)
    baseline = understand(req)
    from app.semantics.semantic_intent_model import should_use_semantic_model, describe_with_model
    if not should_use_semantic_model(req, baseline):
        return baseline
    described = await describe_with_model(engine, req)
    if described is None:
        return baseline  # conservative RUNTIME; never silently downgrade to chat
    descriptor, usage = described
    refined = understand(req, descriptor=descriptor)
    return refined.model_copy(update={
        "model_calls": int(usage["model_calls"]),
        "model_tokens": int(usage["model_tokens"]),
        "model_estimated_cost": float(usage["model_estimated_cost"]),
        "model_cost_known": bool(usage["model_cost_known"]),
    })


@app.post("/internal/v1/runtime/interactive-stream")
async def interactive_stream(
    req: InteractiveStreamRequest,
    x_internal_token: str = Header(default=""),
):
    verify_internal(x_internal_token)
    if registry is None:
        raise HTTPException(status_code=503, detail="runtime not ready")

    async def body():
        try:
            async for event in stream_interactive_answer(registry.context, req):
                yield encode_ndjson(event)
        except Exception as exc:
            # The stream may already have started, so transport failures are
            # represented as a terminal event rather than a second HTTP status.
            raw = str(exc).strip()
            if raw.startswith("附件解析失败"):
                public_message = raw[:300]
            else:
                public_message = "模型执行失败，请稍后重试；如果持续失败，请检查当前模型配置。"
            yield encode_ndjson({
                "type": "error",
                "message": public_message,
            })

    return StreamingResponse(
        body(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/internal/v1/runtime/execute-stream")
async def execute_stream(
    req: RuntimeRequest,
    x_internal_token: str = Header(default=""),
):
    verify_internal(x_internal_token)
    if engine is None:
        raise HTTPException(status_code=503, detail="runtime not ready")

    async def body():
        queue: asyncio.Queue[dict] = asyncio.Queue()
        loop = asyncio.get_running_loop()
        client_connected = {"value": True}

        def publish_live(payload: dict):
            if not client_connected["value"]:
                return
            def submit():
                if not client_connected["value"]:
                    return
                queue.put_nowait(payload)
            loop.call_soon_threadsafe(submit)

        def on_trace(trace_event):
            payload = trace_event.model_dump(mode="json", by_alias=True)
            publish_live({"type": "trace", "trace": payload})

        def on_delta(chunk: str):
            if chunk:
                publish_live({"type": "delta", "delta": chunk})

        async def execute_task():
            try:
                response = await run_scoped_runtime(
                    req, event_sink=on_trace, delta_sink=on_delta,
                )
                await queue.put({
                    "type": "result",
                    "result": response.model_dump(mode="json", by_alias=True),
                })
            except Exception as exc:
                await queue.put({
                    "type": "error",
                    "message": str(exc)[:500] or "runtime execution failed",
                })
            finally:
                await queue.put({"type": "_end"})

        task = asyncio.create_task(execute_task())
        try:
            while True:
                item = await queue.get()
                if item.get("type") == "_end":
                    break
                yield encode_ndjson(item)
        finally:
            # Never accumulate an unconsumed event queue after the HTTP client
            # disconnects. The execution task continues; Go still persists the
            # authoritative result when its own connection remains available.
            client_connected["value"] = False
            if not task.done():
                task.add_done_callback(lambda _: None)

    return StreamingResponse(
        body(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


@app.post(
    "/internal/v1/runtime/execute",
    response_model=RuntimeResponse,
)
async def execute(
    req: RuntimeRequest,
    x_internal_token: str = Header(default=""),
):
    verify_internal(x_internal_token)
    try:
        return await run_scoped_runtime(req)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/internal/v1/runtime/executions", status_code=202)
async def submit_durable_execution(
    envelope: DurableExecutionEnvelope,
    x_internal_token: str = Header(default=""),
):
    verify_internal(x_internal_token)
    if execution_manager is None:
        response = HTTPException(status_code=503, detail="runtime worker not enabled")
        response.headers = {"X-AgentMesh-Accepted": "false"}
        raise response
    try:
        accepted = await execution_manager.submit(envelope)
        return accepted.model_dump(mode="json", by_alias=True)
    except WorkerUnavailable as exc:
        response = HTTPException(status_code=exc.status_code, detail=str(exc))
        response.headers = {"X-AgentMesh-Accepted": "false"}
        raise response


@app.delete("/internal/v1/runtime/executions/{execution_id}")
async def cancel_durable_execution(
    execution_id: str,
    x_internal_token: str = Header(default=""),
):
    verify_internal(x_internal_token)
    if execution_manager is None:
        raise HTTPException(status_code=404, detail="execution not found")
    found = await execution_manager.cancel(execution_id)
    if not found:
        raise HTTPException(status_code=404, detail="execution not found")
    return {"canceled": True}


@app.get("/internal/v1/runtime/worker")
async def runtime_worker_status(
    x_internal_token: str = Header(default=""),
):
    verify_internal(x_internal_token)
    if execution_manager is None:
        return {"enabled": False}
    return {
        "enabled": True,
        "workerId": execution_manager.worker_id,
        "nodeId": execution_manager.node_id,
        "zone": execution_manager.node_zone,
        "version": execution_manager.node_version,
        "capacity": execution_manager.capacity,
        "nodeCapacity": execution_manager.node_capacity,
        "activeExecutions": execution_manager.active_count(),
        "draining": execution_manager.draining,
    }


@app.post("/internal/v1/runtime/worker/drain")
async def runtime_worker_drain(
    draining: bool = True,
    x_internal_token: str = Header(default=""),
):
    verify_internal(x_internal_token)
    if execution_manager is None:
        raise HTTPException(status_code=404, detail="runtime worker not enabled")
    await execution_manager.set_draining(draining)
    return {
        "workerId": execution_manager.worker_id,
        "nodeId": execution_manager.node_id,
        "draining": execution_manager.draining,
        "activeExecutions": execution_manager.active_count(),
    }


@app.post("/internal/v1/mcp/discover")
async def discover_mcp(
    req: MCPDiscoverRequest,
    x_internal_token: str = Header(default=""),
):
    verify_internal(x_internal_token)
    try:
        async with MCPManager([req.server]) as manager:
            return {
                "tools": [
                    tool.model_dump(mode="json")
                    for tool in await manager.discover(req.server)
                ]
            }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/internal/v1/knowledge/index")
async def index_knowledge(
    file: UploadFile = File(...),
    user_id: int = Form(..., alias="userId"),
    knowledge_base_id: int = Form(..., alias="knowledgeBaseId"),
    knowledge_file_id: int = Form(..., alias="knowledgeFileId"),
    original_name: str = Form(..., alias="originalName"),
    extension: str = Form(...),
    checksum_sha256: str = Form("", alias="checksumSha256"),
    project_id: int | None = Form(None, alias="projectId"),
    project_model_json: str = Form("", alias="projectModel"),
    x_internal_token: str = Header(default=""),
):
    verify_internal(x_internal_token)
    if knowledge_indexer is None:
        raise HTTPException(status_code=503, detail="knowledge indexer not ready")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="empty knowledge file")
    if len(content) > 25 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="knowledge file too large")

    request = KnowledgeIndexInput(
        user_id=user_id,
        knowledge_base_id=knowledge_base_id,
        knowledge_file_id=knowledge_file_id,
        project_id=project_id,
        original_name=original_name,
        extension=extension,
        checksum_sha256=checksum_sha256,
    )

    request_vision_analyzer = None
    if project_model_json.strip():
        try:
            project_model = ProjectModelRuntime.model_validate_json(project_model_json)
        except ValidationError as exc:
            # The secret-bearing payload is never included in the response/log.
            raise HTTPException(status_code=400, detail="invalid project model runtime") from exc
        request_vision_analyzer = ModelVisionAnalyzer(
            resolve_project_model_runtime(
                project_model,
                require_explicit_vision=True,
            )
        )

    try:
        result = await knowledge_indexer.index_detailed(
            request,
            content,
            vision_analyzer_override=request_vision_analyzer,
        )
        return {
            "chunkCount": result.stats.total_documents,
            "textChunkCount": result.stats.text_chunks,
            "visualEvidenceCount": result.stats.visual_evidence,
            "pageCount": result.stats.page_count,
            "visualStatus": result.stats.visual_status,
            "visualError": result.stats.visual_error,
            "knowledgeFileId": knowledge_file_id,
            "knowledgeBaseId": knowledge_base_id,
        }
    except Exception as exc:
        # The Go control plane persists this error in the knowledge file lifecycle.
        # Never surface raw provider exception text because it can contain request
        # URLs, Authorization headers, or API keys.
        raise HTTPException(status_code=422, detail=safe_knowledge_error(exc)) from exc


class KnowledgeDeleteRequest(BaseModel):
    user_id: int = Field(alias="userId")
    knowledge_base_id: int = Field(alias="knowledgeBaseId")
    knowledge_file_id: int = Field(alias="knowledgeFileId")


@app.delete("/internal/v1/knowledge/index")
async def delete_knowledge_index(
    req: KnowledgeDeleteRequest,
    x_internal_token: str = Header(default=""),
):
    verify_internal(x_internal_token)
    if knowledge_indexer is None:
        raise HTTPException(status_code=503, detail="knowledge indexer not ready")

    try:
        await knowledge_indexer.delete(
            user_id=req.user_id,
            knowledge_base_id=req.knowledge_base_id,
            knowledge_file_id=req.knowledge_file_id,
        )
        return {"deleted": True}
    except Exception as exc:
        # Deletion failures must be visible to the Control Plane, but raw Milvus
        # errors may contain deployment details. Reuse the redacted knowledge
        # error contract instead of returning a false 200 or raw provider text.
        raise HTTPException(status_code=502, detail=safe_knowledge_error(exc)) from exc
