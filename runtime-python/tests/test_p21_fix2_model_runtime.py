from __future__ import annotations

import pytest
from types import SimpleNamespace

from app.models.providers import MockModelProvider
from app.models.runtime import ModelRuntimeResolver, resolve_project_model_runtime
from app.schemas import AgentProfile, ModelSelection, ProjectModelRuntime


def _mock_service(*, service_id: int = 6) -> ProjectModelRuntime:
    return ProjectModelRuntime.model_validate({
        "serviceId": service_id,
        "serviceName": "P21 QA Mock",
        "provider": "mock",
        "baseUrl": "https://example.invalid/v1",
        "modelName": "agentmesh-qa-mock",
        "apiKey": "synthetic-not-used",
        "autoRoute": True,
        "isDefault": True,
    })


@pytest.mark.asyncio
async def test_project_mock_model_runtime_is_local_and_deterministic() -> None:
    runtime = resolve_project_model_runtime(_mock_service())

    assert isinstance(runtime.gateway.provider, MockModelProvider)
    assert runtime.gateway_provider == "mock"
    assert runtime.declared_provider == "mock"
    text = await runtime.generate("P21 FIX2 deterministic mock request")
    assert text.startswith("[Mock Answer]")


def test_user_model_pool_mock_candidate_does_not_build_http_provider() -> None:
    resolver = ModelRuntimeResolver(SimpleNamespace(services={}))
    agent = AgentProfile.model_validate({
        "id": 21,
        "name": "P21 QA Agent",
        "description": "qa",
        "endpoint": "local://p21-qa",
        "capabilities": ["general"],
        "modelRuntime": "default",
        "modelName": "agentmesh-qa-mock",
        "provider": "mock",
    })

    resolved = resolver.resolve(
        agent,
        model_pool=[_mock_service()],
        model_selection=ModelSelection(mode="auto"),
    )

    assert isinstance(resolved.gateway.provider, MockModelProvider)
    assert resolved.gateway_provider == "mock"
    assert resolved.declared_provider == "mock"
