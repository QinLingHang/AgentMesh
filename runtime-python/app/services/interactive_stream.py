from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator
from typing import Any

from app.config import settings
from app.knowledge.parser import parse_document_bytes
from app.kernel import RuntimeContext
from app.models import ModelInputAttachment, ModelMessage, ModelRequest
from app.models.providers import OpenAICompatibleModelProvider
from app.schemas import InteractiveStreamRequest


_SYSTEM_PROMPT = """你是 AgentMesh 的交互式回答模型。

要求：
1. 对普通知识问题直接使用模型自身知识回答，不要求项目知识库提供证据。
2. 如果本轮提供了附件，优先基于附件内容回答；不要声称看不到已经成功传入的附件。
3. 回答使用自然、清晰的 Markdown；不要输出 HTML <br> 标签。
4. 不暴露内部路由、Agent 调度、Provider、Trace 等实现细节，除非用户明确询问。
5. 不确定时明确说明不确定之处，不要编造附件中不存在的事实。
6. 默认简洁但完整；只有用户要求时再展开很长的解释。
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


def _build_provider_and_model(
    context: RuntimeContext,
    req: InteractiveStreamRequest,
    has_images: bool,
):
    if req.project_model is not None:
        provider = OpenAICompatibleModelProvider(
            api_key=req.project_model.api_key.get_secret_value(),
            base_url=req.project_model.base_url,
            trust_env=False,
        )
        model = req.project_model.model_name
        if has_images and req.project_model.vision_model_name:
            model = req.project_model.vision_model_name
        return provider, model

    runtime = context.get("model.runtime.default")
    provider = runtime.gateway.provider
    model = runtime.vision_model if has_images and runtime.vision_model else runtime.model
    return provider, model


def _bounded_history(req: InteractiveStreamRequest) -> list[ModelMessage]:
    # The Go control plane already performs a first truncation. Keep a second
    # runtime-side budget so one large previous document answer cannot poison
    # latency for the next ordinary question.
    budget = 6000
    selected: list[ModelMessage] = []
    for message in reversed(req.history[-8:]):
        content = " ".join(message.content.split()).strip()
        if not content:
            continue
        remaining = budget - sum(len(item.content) for item in selected)
        if remaining <= 0:
            break
        content = content[: min(1400, remaining)]
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
    provider, model = _build_provider_and_model(context, req, bool(image_attachments))

    user_content = req.task.strip()
    if document_context:
        user_content = (
            f"{user_content}\n\n"
            "下面是本轮用户刚刚上传、仅用于当前请求的附件内容。请优先基于它回答：\n\n"
            f"{document_context}"
        )

    messages = [ModelMessage(role="system", content=_SYSTEM_PROMPT)]
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

    yield {
        "type": "ready",
        "model": model,
        "attachments": notices,
        "mode": "interactive_stream",
    }

    stream_method = getattr(provider, "stream", None)
    if stream_method is None:
        # All built-in production providers implement stream. This fallback
        # keeps custom test providers compatible without pretending to stream.
        response = await provider.generate(request)
        if response.content:
            yield {"type": "delta", "delta": response.content}
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

    async for event in stream_method(request):
        yield event


def encode_ndjson(event: dict[str, Any]) -> bytes:
    return (json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
