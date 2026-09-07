import pytest

from app.models.runtime import (
    ModelRuntimeResolutionError,
    ModelRuntimeResolver,
)
from app.schemas import (
    AgentProfile,
    RuntimeRequest,
)
from app.services import (
    RuntimeEngine,
    create_registry,
)


def create_agent(
    *,
    model_name: str,
    model_runtime: str = "default",
) -> AgentProfile:
    return AgentProfile(
        id=7001,
        name="ModelRoutingAgent",
        endpoint="internal://model-routing",
        protocol="internal",
        capabilities=[
            "general",
        ],
        provider="test-provider",
        modelName=model_name,
        modelRuntime=model_runtime,
    )


@pytest.mark.asyncio
async def test_agent_model_name_overrides_default():
    registry = await create_registry()

    try:
        default_model = (
            registry.context
            .get("model.default")
        )

        original_model = (
            default_model.model
        )

        resolver = ModelRuntimeResolver(
            registry.context
        )

        resolved = resolver.resolve(
            create_agent(
                model_name=(
                    "agent-specific-model"
                )
            )
        )

        assert (
            resolved.model
            == "agent-specific-model"
        )

        assert (
            default_model.model
            == original_model
        )

        assert (
            resolved.gateway
            is default_model.gateway
        )

    finally:
        await registry.stop_all()


@pytest.mark.asyncio
async def test_runtime_uses_agent_model_binding():
    registry = await create_registry()

    try:
        engine = RuntimeEngine(
            registry
        )

        result = await engine.run(
            RuntimeRequest(
                user_id=1,
                request_id=(
                    "model-routing-test"
                ),
                task=(
                    "Explain an AI agent."
                ),
                scheduler="fixed",
                agents=[
                    create_agent(
                        model_name=(
                            "agent-specific-model"
                        )
                    )
                ],
            )
        )

        route_events = [
            item
            for item in result.trace
            if item.kind
            == "model_route"
        ]

        assert route_events

        assert (
            "agent-specific-model"
            in route_events[0].detail
        )

        assert any(
            item.kind == "model"
            and (
                "agent-specific-model"
                in item.detail
            )
            for item in result.trace
        )

    finally:
        await registry.stop_all()

class _CaptureGateway:
    def __init__(self) -> None:
        self.requests = []

    async def generate(self, request, on_event=None):
        from app.models import ModelResponse

        self.requests.append(request)
        return ModelResponse(
            content="ok",
            provider="capture",
            model=request.model,
        )


@pytest.mark.asyncio
async def test_resolved_runtime_uses_vision_model_for_image_attachments():
    from app.models import ModelInputAttachment
    from app.models.runtime import ResolvedModelRuntime

    gateway = _CaptureGateway()
    runtime = ResolvedModelRuntime(
        runtime_id="default",
        gateway=gateway,
        gateway_provider="capture",
        declared_provider="capture",
        model="qwen-plus",
        vision_model="qwen-vl-plus",
        plugin=object(),
    )

    await runtime.generate_response(
        "Describe this screenshot.",
        attachments=[
            ModelInputAttachment(
                name="screen.png",
                media_type="image/png",
                content_base64="aGVsbG8=",
            )
        ],
    )

    assert gateway.requests[-1].model == "qwen-vl-plus"
    assert len(gateway.requests[-1].attachments) == 1


@pytest.mark.asyncio
async def test_resolved_runtime_keeps_text_model_without_image_attachments():
    from app.models.runtime import ResolvedModelRuntime

    gateway = _CaptureGateway()
    runtime = ResolvedModelRuntime(
        runtime_id="default",
        gateway=gateway,
        gateway_provider="capture",
        declared_provider="capture",
        model="qwen-plus",
        vision_model="qwen-vl-plus",
        plugin=object(),
    )

    await runtime.generate_response("Explain Python.")

    assert gateway.requests[-1].model == "qwen-plus"
    assert gateway.requests[-1].attachments == []
