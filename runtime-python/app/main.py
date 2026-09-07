from contextlib import asynccontextmanager

from fastapi import (
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    UploadFile,
)
from pydantic import BaseModel, Field
from fastapi.responses import StreamingResponse

from app.config import settings
from app.distributed import (
    DurableExecutionEnvelope,
    DurableExecutionManager,
    WorkerUnavailable,
)
from app.knowledge import (
    KnowledgeIndexer,
    KnowledgeScope,
    KnowledgeScopeClient,
    install_scoped_retriever,
    reset_knowledge_scope,
    set_knowledge_scope,
)
from app.knowledge.indexer import KnowledgeIndexInput
from app.mcp import MCPDiscoverRequest, MCPManager
from app.schemas import InteractiveStreamRequest, RuntimeRequest, RuntimeResponse
from app.services import RuntimeEngine, create_registry
from app.services.interactive_stream import encode_ndjson, stream_interactive_answer

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
    knowledge_indexer = KnowledgeIndexer(base_retriever)
    knowledge_scope_client = KnowledgeScopeClient(
        internal_token=settings.internal_token,
    )

    if settings.runtime_worker_enabled:
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
        "draining": execution_manager.draining if execution_manager is not None else False,
        "activeExecutions": execution_manager.active_count() if execution_manager is not None else 0,
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
    if knowledge_scope_client is None:
        raise HTTPException(status_code=503, detail="knowledge scope client not ready")

    try:
        return await knowledge_scope_client.resolve(
            user_id=req.user_id,
            conversation_id=req.conversation_id,
        )
    except Exception as exc:
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


async def run_scoped_runtime(req: RuntimeRequest) -> RuntimeResponse:
    if engine is None:
        raise HTTPException(status_code=503, detail="runtime not ready")

    scope = await resolve_request_scope(req)
    token = set_knowledge_scope(scope)
    try:
        return await engine.run(req)
    finally:
        reset_knowledge_scope(token)


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
        "capacity": execution_manager.capacity,
        "activeExecutions": execution_manager.active_count(),
        "draining": execution_manager.draining,
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

    try:
        count = await knowledge_indexer.index(request, content)
        return {
            "chunkCount": count,
            "knowledgeFileId": knowledge_file_id,
            "knowledgeBaseId": knowledge_base_id,
        }
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


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
        raise HTTPException(status_code=502, detail=str(exc)) from exc
