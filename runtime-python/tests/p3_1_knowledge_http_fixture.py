"""Test-only HTTP host for real Knowledge indexing and scoped retrieval.

Started and stopped by the Go P3.1 integration suite. Uses production index
routes, parser, indexer, retriever and Go scope callback; no Memory behavior is
implemented here and no production application file is changed.
"""
from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uvicorn
from fastapi import FastAPI, Header
from pydantic import BaseModel

from app import main
from app.knowledge.indexer import KnowledgeIndexer
from app.knowledge.scope import KnowledgeScopeClient, ScopedRetriever, reset_knowledge_scope, set_knowledge_scope
from app.rag.runtime import InMemoryRetriever


class RetrievalProbe(BaseModel):
    control_url: str
    user_id: int
    conversation_id: int


def create_fixture_app():
    backend = InMemoryRetriever([])
    main.knowledge_indexer = KnowledgeIndexer(backend)
    fixture = FastAPI()

    @fixture.post("/test/retrieve")
    async def retrieve(probe: RetrievalProbe, x_internal_token: str = Header(default="")):
        main.verify_internal(x_internal_token)
        scope = await KnowledgeScopeClient(
            base_url=probe.control_url, internal_token=main.settings.internal_token
        ).resolve(user_id=probe.user_id, conversation_id=probe.conversation_id)
        token = set_knowledge_scope(scope)
        try:
            hits = await ScopedRetriever(backend).retrieve("AgentMesh evidence", top_k=20)
            return {"mode": scope.mode, "projectId": scope.project_id,
                    "fileIds": sorted({hit.document.metadata["knowledgeFileId"] for hit in hits})}
        finally:
            reset_knowledge_scope(token)

    fixture.mount("/", main.app)
    return fixture


if __name__ == "__main__":
    app = create_fixture_app()
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    print(json.dumps({"port": listener.getsockname()[1]}), flush=True)
    # Do not start the production engine/plugins: this host exercises only
    # Knowledge I/O with the supported deterministic retrieval backend.
    uvicorn.Server(uvicorn.Config(app, lifespan="off", access_log=False, log_level="error")).run(sockets=[listener])
