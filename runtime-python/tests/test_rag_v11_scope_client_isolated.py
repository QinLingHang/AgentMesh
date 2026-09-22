"""Exercise the real scope client without requiring optional RAG embeddings/MCP deps.

This imports the production scope.py with its optional RetrievalHit type-only
import replaced by a lightweight test-only placeholder; no production module
or behavior is monkeypatched and no network request leaves the process.
"""
import asyncio
import ast
from pathlib import Path
import types

import httpx
import pytest


_SOURCE = Path(__file__).resolve().parents[1] / "app" / "knowledge" / "scope.py"


def load_scope():
    source = _SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(_SOURCE))
    tree.body = [node for node in tree.body if not (
        isinstance(node, ast.ImportFrom) and node.module == "app.rag.runtime"
    )]
    module = types.ModuleType("isolated_scope_client")
    module.__file__ = str(_SOURCE)
    module.__dict__["RetrievalHit"] = object
    # dataclasses with postponed type annotations do not need a package import.
    import sys
    sys.modules[module.__name__] = module
    exec(compile(tree, str(_SOURCE), "exec"), module.__dict__)
    return module


def mock_client(monkeypatch, module, callback):
    genuine = httpx.AsyncClient
    transport = httpx.MockTransport(callback)

    def factory(*args, **kwargs):
        kwargs.pop("trust_env", None)
        return genuine(*args, transport=transport, trust_env=False, **kwargs)

    monkeypatch.setattr(module.httpx, "AsyncClient", factory)


def test_scope_resolution_returns_a_scope_not_none(monkeypatch):
    module = load_scope()
    def handle(request):
        assert request.url.path == "/internal/v1/knowledge/scope"
        assert request.headers.get("X-Internal-Token") == "test-internal"
        return httpx.Response(200, json={"data": {
            "userId": 8, "conversationId": 22, "projectId": 3,
            "knowledgeBaseIds": [12, 14], "mode": "PROJECT",
        }})
    mock_client(monkeypatch, module, handle)
    result = asyncio.run(module.KnowledgeScopeClient(
        internal_token="test-internal", base_url="http://127.0.0.1:8086",
    ).resolve(user_id=8, conversation_id=22))
    assert isinstance(result, module.KnowledgeScope)
    assert (result.user_id, result.project_id, result.mode) == (8, 3, "PROJECT")
    assert result.knowledge_base_ids == (12, 14)


def test_realtime_authorization_never_expands_request(monkeypatch):
    module = load_scope()
    def handle(request):
        assert request.url.path == "/internal/v1/knowledge/authorize"
        return httpx.Response(200, json={"data": {"knowledgeBaseIds": [14, 15, 999]}})
    mock_client(monkeypatch, module, handle)
    result = asyncio.run(module.KnowledgeScopeClient(
        internal_token="test-internal", base_url="http://127.0.0.1:8086",
    ).authorize(8, 22, (12, 14)))
    assert result == (14,)


def test_malformed_authority_reply_fails_closed(monkeypatch):
    module = load_scope()
    mock_client(monkeypatch, module, lambda _: httpx.Response(200, json={"data": {}}))
    with pytest.raises(ValueError, match="invalid live knowledge authorization"):
        asyncio.run(module.KnowledgeScopeClient(
            internal_token="test-internal", base_url="http://127.0.0.1:8086",
        ).authorize(8, 22, (12,)))
