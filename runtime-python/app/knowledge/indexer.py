from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from app.multimodal.contracts import VisionAnalyzer
from app.multimodal.ingestion import MultimodalIngestionResult, ingest_multimodal_document
from app.rag.runtime import RetrievalDocument


@dataclass(frozen=True, slots=True)
class KnowledgeIndexInput:
    user_id: int
    knowledge_base_id: int
    knowledge_file_id: int
    project_id: int | None
    original_name: str
    extension: str
    checksum_sha256: str


class KnowledgeIndexer:
    def __init__(self, backend, vision_analyzer: VisionAnalyzer | None = None) -> None:
        self.backend = backend
        self.vision_analyzer = vision_analyzer

    def _base_metadata(self, request: KnowledgeIndexInput) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "userId": request.user_id,
            "knowledgeBaseId": request.knowledge_base_id,
            "knowledgeFileId": request.knowledge_file_id,
            "documentId": f"knowledge-file-{request.knowledge_file_id}",
            "documentType": request.extension,
            "checksumSha256": request.checksum_sha256,
        }
        if request.project_id is not None:
            metadata["projectId"] = request.project_id
        return metadata

    async def index_detailed(
        self,
        request: KnowledgeIndexInput,
        content: bytes,
        *,
        vision_analyzer_override: VisionAnalyzer | None = None,
    ) -> MultimodalIngestionResult:
        await self.delete(
            user_id=request.user_id,
            knowledge_base_id=request.knowledge_base_id,
            knowledge_file_id=request.knowledge_file_id,
        )

        result = await ingest_multimodal_document(
            content=content,
            extension=request.extension,
            source=request.original_name,
            base_metadata=self._base_metadata(request),
            vision_analyzer=(vision_analyzer_override or self.vision_analyzer),
        )

        documents: list[RetrievalDocument] = result.documents
        upsert = getattr(self.backend, "upsert_documents", None)
        if upsert is not None:
            count = await upsert(documents)
            if int(count or len(documents)) <= 0:
                raise RuntimeError("configured RAG backend returned zero indexed evidence")
            return result

        add_documents = getattr(self.backend, "add_documents", None)
        if add_documents is not None:
            add_documents(documents)
            return result

        raise RuntimeError("configured RAG backend does not support ingestion")

    async def index(
        self,
        request: KnowledgeIndexInput,
        content: bytes,
    ) -> int:
        """Backward-compatible P1 contract: return total indexed evidence count."""
        result = await self.index_detailed(request, content)
        return result.stats.total_documents

    async def delete(
        self,
        *,
        user_id: int,
        knowledge_base_id: int,
        knowledge_file_id: int,
    ) -> None:
        # Prefer the backend's public deletion contract when available. This is
        # important for persistent/hybrid backends: inspecting a private
        # in-memory cache must never short-circuit deletion from Milvus.
        delete_documents = getattr(self.backend, "delete_documents", None)
        if delete_documents is not None:
            await delete_documents(
                filters={
                    "userId": user_id,
                    "knowledgeBaseId": knowledge_base_id,
                    "knowledgeFileId": knowledge_file_id,
                }
            )
            return

        # In-memory deterministic baseline.
        memory = getattr(self.backend, "_documents", None)
        if isinstance(memory, dict):
            remove = [
                key
                for key, document in memory.items()
                if document.metadata.get("userId") == user_id
                and document.metadata.get("knowledgeBaseId") == knowledge_base_id
                and document.metadata.get("knowledgeFileId") == knowledge_file_id
            ]
            for key in remove:
                memory.pop(key, None)
            return

        # Compatibility fallback for older Milvus-like backends. Keep the
        # expression aligned with the current explicit collection schema:
        # user_id is a top-level INT64 field; knowledge IDs live in metadata.
        client = getattr(self.backend, "client", None) or getattr(self.backend, "_client", None)
        collection_name = getattr(self.backend, "collection_name", None) or getattr(self.backend, "_collection_name", None)

        if client is None or not collection_name:
            return

        delete = getattr(client, "delete", None)
        if delete is None:
            return

        expression = (
            f"user_id == {int(user_id)} and "
            f'metadata["knowledgeBaseId"] == {int(knowledge_base_id)} and '
            f'metadata["knowledgeFileId"] == {int(knowledge_file_id)}'
        )

        def do_delete() -> None:
            try:
                delete(collection_name=collection_name, filter=expression)
            except TypeError:
                delete(collection_name, filter=expression)

        # Do not translate schema/filter errors into success. A failed delete
        # must propagate so the Control Plane cannot report a false cleanup.
        await asyncio.to_thread(do_delete)
