from __future__ import annotations

import base64
import io
import json
from dataclasses import dataclass

import httpx
from docx import Document
from pypdf import PdfReader

from app.models import ModelMessage, ModelRequest
from app.models.contracts import ModelImagePart, ModelImageURL, ModelTextPart
from app.models.providers import MockModelProvider, OpenAICompatibleModelProvider
from app.models.gateway import ModelGateway
from app.schemas import RuntimeAttachment, RuntimeRequest

MAX_TOTAL_BYTES = 40 * 1024 * 1024
MAX_EXTRACTED_CHARS = 24000

@dataclass(slots=True)
class LoadedAttachment:
    ref: RuntimeAttachment
    content: bytes

class AttachmentClient:
    def __init__(self, base_url: str, internal_token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.internal_token = internal_token

    async def load(self, user_id: int, ref: RuntimeAttachment) -> LoadedAttachment:
        url = f"{self.base_url}/internal/v1/attachments/{ref.id}"
        async with httpx.AsyncClient(timeout=20.0, trust_env=False) as client:
            response = await client.get(url, params={"userId": user_id}, headers={"X-Internal-Token": self.internal_token})
        response.raise_for_status()
        content = response.content
        if len(content) > 20 * 1024 * 1024:
            raise ValueError("attachment too large")
        return LoadedAttachment(ref=ref, content=content)

async def load_all(client: AttachmentClient, req: RuntimeRequest) -> list[LoadedAttachment]:
    loaded: list[LoadedAttachment] = []
    total = 0
    for ref in req.attachments:
        item = await client.load(req.user_id, ref)
        total += len(item.content)
        if total > MAX_TOTAL_BYTES:
            raise ValueError("attachments exceed total size limit")
        loaded.append(item)
    return loaded

def _extract_document(item: LoadedAttachment) -> str:
    ext = item.ref.name.lower().rsplit(".", 1)[-1] if "." in item.ref.name else ""
    if ext in {"txt", "md", "markdown", "csv", "json"}:
        text = item.content.decode("utf-8", errors="replace")
        if ext == "json":
            try: text = json.dumps(json.loads(text), ensure_ascii=False, indent=2)
            except Exception: pass
        return text[:MAX_EXTRACTED_CHARS]
    if ext == "pdf":
        reader = PdfReader(io.BytesIO(item.content))
        return "\n".join((page.extract_text() or "") for page in reader.pages)[:MAX_EXTRACTED_CHARS]
    if ext == "docx":
        doc = Document(io.BytesIO(item.content))
        return "\n".join(p.text for p in doc.paragraphs)[:MAX_EXTRACTED_CHARS]
    return ""

async def _describe_image(item: LoadedAttachment, req: RuntimeRequest, engine) -> str:
    data_url = f"data:{item.ref.media_type};base64,{base64.b64encode(item.content).decode('ascii')}"
    if req.project_model is not None:
        normalized_provider = req.project_model.provider.strip().lower().replace("_", "-")
        if normalized_provider == "mock":
            provider = MockModelProvider()
        else:
            provider = OpenAICompatibleModelProvider(
                api_key=req.project_model.api_key.get_secret_value(),
                base_url=req.project_model.base_url,
                trust_env=False,
            )
        gateway = ModelGateway(provider, timeout=30.0, max_retries=1)
        model = req.project_model.model_name
    else:
        default = engine.registry.context.get("model.default")
        gateway = default.gateway
        model = default.model
    response = await gateway.generate(ModelRequest(model=model, messages=[
        ModelMessage(role="system", content="You analyze user-provided images for an Agent workflow. Describe only observable information and text relevant to the user's task."),
        ModelMessage(role="user", content=[
            ModelTextPart(text=f"User task: {req.task}\nImage file: {item.ref.name}\nAnalyze this image accurately."),
            ModelImagePart(image_url=ModelImageURL(url=data_url)),
        ]),
    ], temperature=0.1))
    return response.content[:MAX_EXTRACTED_CHARS]

async def enrich_task_with_attachments(req: RuntimeRequest, loaded: list[LoadedAttachment], engine) -> RuntimeRequest:
    if not loaded: return req
    sections: list[str] = []
    for item in loaded:
        if item.ref.kind == "image":
            observation = await _describe_image(item, req, engine)
            sections.append(f"[图片附件: {item.ref.name}]\n{observation}")
        else:
            extracted = _extract_document(item)
            sections.append(f"[文件附件: {item.ref.name}]\n{extracted or '(未能提取可读文本，请根据文件元数据说明限制)'}")
    context = "\n\n".join(sections)
    task = f"{req.task}\n\n以下是用户本轮消息直接附加的内容。它们只属于本次任务，不代表长期知识库：\n{context}"
    return req.model_copy(update={"task": task[:60000]})
