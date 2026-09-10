from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator
from typing import Any

from app.config import settings
from app.knowledge.parser import parse_document_bytes
from app.kernel import RuntimeContext
from app.memory.conversation_context import (
    ControlPlaneConversationMemoryStore,
    ConversationMemoryRetriever,
    ModelBackedConversationCompactor,
    render_retrieved_conversation_memories,
)
from app.models import ModelInputAttachment, ModelMessage, ModelRequest
from app.models.runtime import ModelRuntimeResolver
from app.schemas import AgentProfile, InteractiveStreamRequest, TaskProfile


_CONVERSATION_MEMORY_STORE = ControlPlaneConversationMemoryStore(
    internal_token=settings.internal_token,
    base_url=settings.control_plane_internal_base_url,
    timeout_seconds=settings.memory_retrieval_timeout_seconds,
)
_CONVERSATION_MEMORY_RETRIEVER = ConversationMemoryRetriever(
    store=_CONVERSATION_MEMORY_STORE,
    enabled=settings.conversation_memory_retrieval_enabled,
    candidate_limit=settings.conversation_memory_retrieval_candidate_limit,
    top_k=settings.conversation_memory_retrieval_top_k,
    min_score=settings.conversation_memory_retrieval_min_score,
    max_chars=settings.conversation_memory_retrieval_max_chars,
)
_CONVERSATION_MEMORY_COMPACTOR = ModelBackedConversationCompactor(
    store=_CONVERSATION_MEMORY_STORE,
    enabled=settings.conversation_memory_compaction_enabled,
    min_messages=settings.conversation_memory_compaction_min_messages,
    max_messages=settings.conversation_memory_compaction_max_messages,
    reserve_recent=settings.conversation_memory_compaction_reserve_recent,
    min_input_chars=settings.conversation_memory_compaction_min_input_chars,
    max_input_chars=settings.conversation_memory_compaction_max_input_chars,
    max_output_tokens=settings.conversation_memory_compaction_max_output_tokens,
    timeout_seconds=settings.conversation_memory_compaction_timeout_seconds,
    failure_backoff_seconds=settings.conversation_memory_compaction_failure_backoff_seconds,
    redis_url=settings.redis_url,
    lock_prefix=settings.conversation_memory_compaction_lock_prefix,
    lock_ttl_seconds=settings.conversation_memory_compaction_lock_ttl_seconds,
)


_SYSTEM_PROMPT = """你是 AgentMesh 的交互式回答模型。

要求：
1. 对普通知识问题直接使用模型自身知识回答，不要求项目知识库提供证据。
2. 如果本轮提供了附件，优先基于附件内容回答；不要声称看不到已经成功传入的附件。
3. 回答使用自然、清晰的 Markdown；不要输出 HTML <br> 标签。
4. 不暴露内部路由、Agent 调度、Provider、Trace 等实现细节，除非用户明确询问。
5. 不确定时明确说明不确定之处，不要编造附件中不存在的事实。
6. 默认简洁但完整；只有用户要求时再展开很长的解释。
7. 对“继续”“可以”“好的”“展开讲讲”“然后呢”以及单独的“1/2/3/A/B”等选项回复，必须优先承接最近一轮助手给出的选项、问题或未完成任务继续；不要把这类短回复当成新话题，也不要跳回更早的无关话题。
8. 如果用户询问“当前 AgentMesh/这个系统/这个平台”实际具备哪些菜单、插件、工作流、权限、域名、版本或能否直接执行操作，本快速通道没有权威 Capability Registry 快照。不得根据模型先验编造这些产品事实；应明确说明当前快速通道无法确认实例能力，并避免虚构 UI 路径、YAML Schema、插件名、版本、域名或“无法操作电脑”的通用免责声明。此类请求正常情况下应由控制面路由到 Full Runtime。
"""


def _safe_document_context(req: InteractiveStreamRequest) -> tuple[str, list[ModelInputAttachment], list[dict[str, Any]]]:
    text_parts: list[str] = []
    images: list[ModelInputAttachment] = []
    notices: list[dict[str, Any]] = []
    total_chars = 0
    max_chars = 48_000

    for attachment in req.attachments:
        try:
            raw = base64.b64decode(attachment.content_base64, validate=True)
        except Exception:
            notices.append({"name": attachment.name, "status": "error", "reason": "invalid_base64"})
            continue

        if len(raw) != attachment.size_bytes:
            notices.append({"name": attachment.name, "status": "error", "reason": "size_mismatch"})
            continue

        if attachment.media_type.startswith("image/"):
            images.append(
                ModelInputAttachment(
                    name=attachment.name,
                    media_type=attachment.media_type,
                    content_base64=attachment.content_base64,
                )
            )
            notices.append({"name": attachment.name, "status": "ready", "kind": "image"})
            continue

        try:
            text = parse_document_bytes(extension=attachment.extension, content=raw)
        except Exception as exc:
            notices.append({
                "name": attachment.name,
                "status": "error",
                "reason": "parse_failed",
                "detail": str(exc)[:180],
            })
            continue

        remaining = max_chars - total_chars
        if remaining <= 0:
            notices.append({"name": attachment.name, "status": "truncated", "kind": "document"})
            continue
        bounded = text[:remaining]
        total_chars += len(bounded)
        text_parts.append(f"[当前附件：{attachment.name}]\n{bounded}")
        notices.append({
            "name": attachment.name,
            "status": "ready",
            "kind": "document",
            "chars": len(bounded),
            "truncated": len(text) > len(bounded),
        })

    return "\n\n".join(text_parts), images, notices


def _interactive_model_resolver(context: RuntimeContext) -> ModelRuntimeResolver:
    key = "model.resolver.interactive"
    try:
        return context.get(key)
    except KeyError:
        resolver = ModelRuntimeResolver(context)
        try:
            context.provide(key, resolver)
            return resolver
        except RuntimeError:
            # Two first requests may race to initialize the process-local
            # performance store. Reuse the winner instead of failing a request.
            return context.get(key)


def _interactive_profile(req: InteractiveStreamRequest, has_images: bool) -> TaskProfile:
    length = len(req.task.strip())
    complexity = "high" if length > 1800 else ("medium" if length > 400 else "low")
    return TaskProfile(
        required_capabilities=["general"],
        complexity=complexity,
        risk_level="low",
        modality=["text", "image"] if has_images else ["text"],
        parallelizable=False,
    )


def _resolve_provider_and_model(
    context: RuntimeContext,
    req: InteractiveStreamRequest,
    has_images: bool,
):
    resolver = _interactive_model_resolver(context)
    resolved = resolver.resolve(
        AgentProfile(
            id=0,
            name="InteractiveFastPath",
            endpoint="internal://interactive",
            protocol="internal",
            capabilities=["general"],
            modelRuntime="adaptive",
        ),
        adaptive=req.scheduler == "adaptive",
        constraints=req.constraints,
        profile=_interactive_profile(req, has_images),
        project_model=req.project_model,
        model_pool=req.model_pool,
        model_selection=req.model_selection,
        has_images=has_images,
    )
    model = resolved.vision_model if has_images and resolved.vision_model else resolved.model
    return resolved, resolved.gateway.provider, model


def _bounded_history(req: InteractiveStreamRequest) -> list[ModelMessage]:
    # The Go control plane already performs a first truncation. Keep a second
    # runtime-side budget so one large previous document answer cannot poison
    # latency for the next ordinary question.
    budget = 6000
    max_messages = 20
    selected: list[ModelMessage] = []
    for message in reversed(req.history):
        if len(selected) >= max_messages:
            break
        content = " ".join(message.content.split()).strip()
        if not content:
            continue
        remaining = budget - sum(len(item.content) for item in selected)
        if remaining <= 0:
            break
        limit = min(1400, remaining)
        if len(content) > limit:
            head = max(1, limit // 3)
            tail = max(1, limit - head)
            content = content[:head] + " …[中间省略]… " + content[-tail:]
        selected.append(ModelMessage(role=message.role, content=content))
    selected.reverse()
    return selected


async def stream_interactive_answer(
    context: RuntimeContext,
    req: InteractiveStreamRequest,
) -> AsyncIterator[dict[str, Any]]:
    document_context, image_attachments, notices = _safe_document_context(req)
    if req.attachments and not document_context and not image_attachments:
        failed = ", ".join(item.get("name", "附件") for item in notices if item.get("status") == "error")
        raise ValueError(f"附件解析失败：{failed or '请重新上传文件'}")
    resolved, provider, model = _resolve_provider_and_model(context, req, bool(image_attachments))

    user_content = req.task.strip()
    if document_context:
        user_content = (
            f"{user_content}\n\n"
            "下面是本轮用户刚刚上传、仅用于当前请求的附件内容。请优先基于它回答：\n\n"
            f"{document_context}"
        )

    conversation_memory_context = ""
    if req.conversation_id is not None:
        try:
            recalled = await _CONVERSATION_MEMORY_RETRIEVER.retrieve(
                user_id=req.user_id,
                conversation_id=req.conversation_id,
                query=req.task,
            )
            conversation_memory_context = render_retrieved_conversation_memories(recalled)
        except Exception:
            conversation_memory_context = ""

    messages = [ModelMessage(role="system", content=_SYSTEM_PROMPT)]
    if conversation_memory_context:
        messages.append(ModelMessage(role="system", content=conversation_memory_context))
    messages.extend(_bounded_history(req))
    messages.append(ModelMessage(role="user", content=user_content))

    request = ModelRequest(
        model=model,
        messages=messages,
        temperature=0.2,
        max_tokens=1800,
        timeout=min(max(settings.model_timeout_seconds, 8.0), 60.0),
        attachments=image_attachments,
    )

    route_reason = (
        resolved.route_decision.reason
        if resolved.route_decision is not None
        else (
            "用户手动指定模型"
            if resolved.selection_mode == "manual"
            else "使用默认或项目模型配置"
        )
    )
    yield {
        "type": "model_route",
        "model": model,
        "provider": resolved.declared_provider,
        "mode": resolved.selection_mode,
        "reason": route_reason,
        "serviceId": resolved.service_id,
        "serviceName": resolved.service_name,
    }

    yield {
        "type": "ready",
        "model": model,
        "provider": resolved.declared_provider,
        "attachments": notices,
        "mode": "interactive_stream",
        "serviceId": resolved.service_id,
        "serviceName": resolved.service_name,
    }

    stream_method = getattr(provider, "stream", None)
    if stream_method is None:
        # All built-in production providers implement stream. This fallback
        # keeps custom test providers compatible without pretending to stream.
        try:
            response = await provider.generate(request)
        except Exception:
            if resolved.router is not None:
                resolved.router.performance.record_execution(
                    resolved.runtime_id,
                    resolved.plugin,
                    success=False,
                    latency_ms=0,
                    cost=None,
                )
            raise
        if resolved.router is not None:
            resolved.router.performance.record_execution(
                resolved.runtime_id,
                resolved.plugin,
                success=True,
                latency_ms=response.latency_ms,
                cost=response.estimated_cost,
            )
        if response.content:
            yield {"type": "delta", "delta": response.content}
        _CONVERSATION_MEMORY_COMPACTOR.schedule(
            user_id=req.user_id,
            conversation_id=req.conversation_id,
            model_gateway=provider,
            model_name=(settings.conversation_memory_compaction_model_name.strip() or model),
        )
        yield {
            "type": "done",
            "content": response.content,
            "model": response.model,
            "provider": response.provider,
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "total_tokens": response.total_tokens,
            "latency_ms": response.latency_ms,
            "estimated_cost": response.estimated_cost,
        }
        return

    try:
        async for event in stream_method(request):
            if event.get("type") == "done":
                _CONVERSATION_MEMORY_COMPACTOR.schedule(
                    user_id=req.user_id,
                    conversation_id=req.conversation_id,
                    model_gateway=provider,
                    model_name=(settings.conversation_memory_compaction_model_name.strip() or model),
                )
            if event.get("type") == "done" and resolved.router is not None:
                resolved.router.performance.record_execution(
                    resolved.runtime_id,
                    resolved.plugin,
                    success=True,
                    latency_ms=max(0, int(event.get("latency_ms") or 0)),
                    cost=(
                        float(event["estimated_cost"])
                        if event.get("estimated_cost") is not None
                        else None
                    ),
                )
            yield event
    except Exception:
        if resolved.router is not None:
            resolved.router.performance.record_execution(
                resolved.runtime_id,
                resolved.plugin,
                success=False,
                latency_ms=0,
                cost=None,
            )
        raise


def encode_ndjson(event: dict[str, Any]) -> bytes:
    return (json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
