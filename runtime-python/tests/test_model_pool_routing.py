from __future__ import annotations

import pytest

from app.kernel import RuntimeContext
from app.models.runtime import ModelRuntimeResolutionError, ModelRuntimeResolver
from app.schemas import AgentProfile, ModelSelection, ProjectModelRuntime, TaskConstraints, TaskProfile


def _agent() -> AgentProfile:
    return AgentProfile(
        id=9101,
        name="ModelPoolAgent",
        endpoint="internal://model-pool",
        protocol="internal",
        capabilities=["general"],
        provider="agentmesh",
        modelRuntime="adaptive",
    )


def _profile(*, image: bool = False) -> TaskProfile:
    return TaskProfile(
        required_capabilities=["general"],
        complexity="medium",
        risk_level="low",
        modality=["text", "image"] if image else ["text"],
        parallelizable=False,
    )


def _constraints() -> TaskConstraints:
    return TaskConstraints(maxLatencyMs=10_000, maxCost=1.0, minQuality=0.0)


def _service(
    service_id: int,
    *,
    name: str,
    model: str,
    vision: str = "",
    default: bool = False,
) -> ProjectModelRuntime:
    return ProjectModelRuntime(
        serviceId=service_id,
        serviceName=name,
        provider="openai-compatible",
        baseUrl="https://models.example.test/v1",
        modelName=model,
        visionModelName=vision,
        apiKey=f"sk-test-{service_id}",
        autoRoute=True,
        isDefault=default,
    )


def test_auto_model_pool_prefers_default_on_cold_start_tie():
    resolver = ModelRuntimeResolver(RuntimeContext())
    resolved = resolver.resolve(
        _agent(),
        adaptive=True,
        constraints=_constraints(),
        profile=_profile(),
        model_pool=[
            _service(1, name="Default Qwen", model="qwen-plus", default=True),
            _service(2, name="Other Model", model="other-model"),
        ],
        model_selection=ModelSelection(mode="auto"),
    )

    assert resolved.service_id == 1
    assert resolved.service_name == "Default Qwen"
    assert resolved.model == "qwen-plus"
    assert resolved.selection_mode == "auto"
    assert resolved.route_decision is not None
    assert resolved.route_decision.mode == "adaptive"


def test_manual_model_pool_pins_owned_request_service():
    resolver = ModelRuntimeResolver(RuntimeContext())
    resolved = resolver.resolve(
        _agent(),
        adaptive=True,
        constraints=_constraints(),
        profile=_profile(),
        model_pool=[
            _service(1, name="First", model="model-a", default=True),
            _service(2, name="Pinned", model="model-b"),
        ],
        model_selection=ModelSelection(mode="manual", serviceId=2),
    )

    assert resolved.service_id == 2
    assert resolved.service_name == "Pinned"
    assert resolved.model == "model-b"
    assert resolved.selection_mode == "manual"
    assert resolved.route_decision is not None
    assert resolved.route_decision.mode == "pinned"


def test_image_auto_route_excludes_services_without_explicit_vision_model():
    resolver = ModelRuntimeResolver(RuntimeContext())
    resolved = resolver.resolve(
        _agent(),
        adaptive=True,
        constraints=_constraints(),
        profile=_profile(image=True),
        model_pool=[
            _service(1, name="Text Only", model="text-only", default=True),
            _service(2, name="Vision", model="text-model", vision="vision-model"),
        ],
        model_selection=ModelSelection(mode="auto"),
        has_images=True,
    )

    assert resolved.service_id == 2
    assert resolved.vision_model == "vision-model"


def test_manual_image_route_fails_closed_for_text_only_service():
    resolver = ModelRuntimeResolver(RuntimeContext())

    with pytest.raises(ModelRuntimeResolutionError, match="vision model"):
        resolver.resolve(
            _agent(),
            adaptive=True,
            constraints=_constraints(),
            profile=_profile(image=True),
            model_pool=[_service(1, name="Text Only", model="text-only", default=True)],
            model_selection=ModelSelection(mode="manual", serviceId=1),
            has_images=True,
        )
