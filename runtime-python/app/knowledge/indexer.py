from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from app.knowledge.parser import parse_document_bytes
from app.rag.ingestion import chunk_text
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
    def __init__(self, backend) -> None:
        self.backend = backend

    async def index(
        self,
        request: KnowledgeIndexInput,
        content: bytes,
    ) -> int:
        text = parse_document_bytes(
            extension=request.extension,
            content=content,
        )

        await self.delete(
            user_id=request.user_id,
            knowledge_base_id=request.knowledge_base_id,
            knowledge_file_id=request.knowledge_file_id,
        )

        project_id = request.project_id
        base_metadata: dict[str, Any] = {
            "userId": request.user_id,
            "knowledgeBaseId": request.knowledge_base_id,
            "knowledgeFileId": request.knowledge_file_id,
            "documentId": f"knowledge-file-{request.knowledge_file_id}",
            "documentType": request.extension,
            "checksumSha256": request.checksum_sha256,
        }
        if project_id is not None:
            base_metadata["projectId"] = project_id

        generated = chunk_text(
            text=text,
            source=request.original_name,
            metadata=base_metadata,
            chunk_size=500,
            overlap=100,
        )

        documents: list[RetrievalDocument] = []
        for index, item in enumerate(generated):
            metadata = {
                **base_metadata,
                **dict(item.metadata),
                "chunkIndex": int(item.metadata.get("chunkIndex", index)),
            }
            metadata.setdefault("start", max(0, index * 400))
            metadata.setdefault(
                "end",
                metadata["start"] + len(item.text),
            )

            documents.append(
                RetrievalDocument(
                    id=(
                        f"kb{request.knowledge_base_id}_"
                        f"file{request.knowledge_file_id}_"
                        f"chunk{index}"
                    ),
                    text=item.text,
                    source=request.original_name,
                    metadata=metadata,
                )
            )

        if not documents:
            raise ValueError("knowledge document produced zero chunks")

        upsert = getattr(self.backend, "upsert_documents", None)
        if upsert is not None:
            count = await upsert(documents)
            return int(count or len(documents))

        add_documents = getattr(self.backend, "add_documents", None)
        if add_documents is not None:
            add_documents(documents)
            return len(documents)

        raise RuntimeError("configured RAG backend does not support ingestion")

    async def delete(
        self,
        *,
        user_id: int,
        knowledge_base_id: int,
        knowledge_file_id: int,
    ) -> None:
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

        client = (
            getattr(self.backend, "client", None)
            or getattr(self.backend, "_client", None)
        )
        collection_name = (
            getattr(self.backend, "collection_name", None)
            or getattr(self.backend, "_collection_name", None)
        )

        if client is None or not collection_name:
            # No collection has been initialized yet: nothing to delete.
            return

        delete = getattr(client, "delete", None)
        if delete is None:
            return

        expression = (
            f"userId == {int(user_id)} and "
            f"knowledgeBaseId == {int(knowledge_base_id)} and "
            f"knowledgeFileId == {int(knowledge_file_id)}"
        )

        def do_delete() -> None:
            try:
                delete(
                    collection_name=collection_name,
                    filter=expression,
                )
            except TypeError:
                delete(
                    collection_name,
                    filter=expression,
                )
            except Exception as exc:
                text = str(exc).lower()
                if "not exist" in text or "not found" in text:
                    return
                raise

        await asyncio.to_thread(do_delete)
