import pytest
from fastapi import HTTPException

import app.main as runtime_main


class _Manager:
    draining = False


@pytest.mark.asyncio
async def test_p10_livez_is_dependency_independent(monkeypatch):
    monkeypatch.setattr(runtime_main, "registry", None)
    monkeypatch.setattr(runtime_main, "engine", None)
    response = await runtime_main.livez()
    assert response == {
        "status": "alive",
        "service": "agentmesh-runtime",
    }


@pytest.mark.asyncio
async def test_p10_readyz_requires_runtime_components(monkeypatch):
    monkeypatch.setattr(runtime_main, "registry", None)
    monkeypatch.setattr(runtime_main, "engine", None)
    monkeypatch.setattr(runtime_main, "knowledge_scope_client", None)
    monkeypatch.setattr(runtime_main, "execution_manager", None)

    with pytest.raises(HTTPException) as exc:
        await runtime_main.readyz()

    assert exc.value.status_code == 503
    assert exc.value.detail["status"] == "not_ready"
    assert exc.value.detail["checks"]["registry"] is False


@pytest.mark.asyncio
async def test_p10_readyz_rejects_draining_worker(monkeypatch):
    manager = _Manager()
    manager.draining = True
    monkeypatch.setattr(runtime_main, "registry", object())
    monkeypatch.setattr(runtime_main, "engine", object())
    monkeypatch.setattr(runtime_main, "knowledge_scope_client", object())
    monkeypatch.setattr(runtime_main, "execution_manager", manager)

    with pytest.raises(HTTPException) as exc:
        await runtime_main.readyz()

    assert exc.value.status_code == 503
    assert exc.value.detail["checks"]["accepting"] is False


@pytest.mark.asyncio
async def test_p10_readyz_accepts_initialized_runtime(monkeypatch):
    monkeypatch.setattr(runtime_main, "registry", object())
    monkeypatch.setattr(runtime_main, "engine", object())
    monkeypatch.setattr(runtime_main, "knowledge_scope_client", object())
    monkeypatch.setattr(runtime_main, "execution_manager", _Manager())

    response = await runtime_main.readyz()

    assert response["status"] == "ready"
    assert all(response["checks"].values())
