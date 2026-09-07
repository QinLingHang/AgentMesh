from __future__ import annotations

import json
from typing import Any

from app.config import settings
from app.kernel import (
    AgentMeshPlugin,
    PluginKind,
    PluginManifest,
    RuntimeContext,
)
from app.models import (
    ModelGateway,
    ModelMessage,
    ModelRequest,
    ModelResponse,
)
from app.models.gateway import ModelEventHandler
from app.models.providers import MockModelProvider, OpenAICompatibleModelProvider


class ModelGatewayPlugin(AgentMeshPlugin):
    def __init__(
        self,
        gateway: ModelGateway,
        model: str,
        runtime_id: str = "default",
        *,
        vision_model: str | None = None,
        routing_quality_score: float = 0.8,
        routing_avg_latency_ms: int = 1000,
        routing_avg_cost: float = 0.0,
        routing_success_rate: float = 1.0,
        routing_sample_count: int = 0,
    ) -> None:
        self.gateway = gateway
        self.model = model
        self.vision_model = (vision_model or "").strip() or None
        self.runtime_id = runtime_id
        self.provider = gateway.provider.name
        self.routing_quality_score = min(max(float(routing_quality_score), 0.0), 1.0)
        self.routing_avg_latency_ms = max(1, int(routing_avg_latency_ms))
        self.routing_avg_cost = max(0.0, float(routing_avg_cost))
        self.routing_success_rate = min(max(float(routing_success_rate), 0.0), 1.0)
        self.routing_sample_count = max(0, int(routing_sample_count))

        plugin_id = "model.gateway" if runtime_id == "default" else f"model.gateway.{runtime_id}"
        self.manifest = PluginManifest(
            plugin_id,
            f"Model Gateway · {self.provider} · {model}",
            "0.4.0",
            PluginKind.MODEL,
        )

    async def setup(self, context: RuntimeContext) -> None:
        context.provide(f"model.runtime.{self.runtime_id}", self)
        if self.runtime_id == "default":
            context.provide("model.default", self)

    async def generate(self, prompt: str, on_event: ModelEventHandler | None = None) -> str:
        response = await self.generate_response(prompt, on_event)
        return response.content

    async def generate_response(
        self,
        prompt: str,
        on_event: ModelEventHandler | None = None,
    ) -> ModelResponse:
        request = ModelRequest(
            model=self.model,
            messages=[
                ModelMessage(role="system", content="You are an AgentMesh Runtime execution model."),
                ModelMessage(role="user", content=prompt),
            ],
            temperature=0.2,
        )
        return await self.gateway.generate(request, on_event)


def _build_provider(
    *,
    provider_name: str,
    api_key: str,
    base_url: str,
    trust_env: bool,
    input_cost_per_million: float,
    output_cost_per_million: float,
):
    normalized = provider_name.strip().lower()
    if normalized == "mock":
        return MockModelProvider()
    if normalized in {"openai_compatible", "qwen"}:
        return OpenAICompatibleModelProvider(
            api_key=api_key,
            base_url=base_url,
            trust_env=trust_env,
            input_cost_per_million=input_cost_per_million,
            output_cost_per_million=output_cost_per_million,
        )
    raise ValueError(f"unsupported MODEL_PROVIDER: {provider_name}")


def create_model_plugin(runtime_id: str = "default") -> ModelGatewayPlugin:
    provider = _build_provider(
        provider_name=settings.model_provider,
        api_key=settings.model_api_key,
        base_url=settings.model_base_url,
        trust_env=settings.model_http_trust_env,
        input_cost_per_million=settings.model_input_cost_per_million,
        output_cost_per_million=settings.model_output_cost_per_million,
    )
    gateway = ModelGateway(
        provider,
        timeout=settings.model_timeout_seconds,
        max_retries=settings.model_max_retries,
    )
    return ModelGatewayPlugin(
        gateway,
        settings.model_name,
        runtime_id=runtime_id,
        vision_model=settings.model_vision_name,
        routing_quality_score=settings.model_routing_default_quality,
        routing_avg_latency_ms=settings.model_routing_default_latency_ms,
        routing_avg_cost=settings.model_routing_default_avg_cost,
        routing_success_rate=settings.model_routing_default_success_rate,
    )


def _float(item: dict[str, Any], key: str, default: float) -> float:
    try:
        return float(item.get(key, default))
    except (TypeError, ValueError):
        return default


def _int(item: dict[str, Any], key: str, default: int) -> int:
    try:
        return int(item.get(key, default))
    except (TypeError, ValueError):
        return default


def create_model_plugins() -> list[ModelGatewayPlugin]:
    """Create the default runtime plus optional P7 routing candidates.

    ``MODEL_RUNTIME_POOL_JSON`` is intentionally optional. A malformed pool is
    rejected at startup rather than silently routing to an unexpected model.
    API keys may be supplied in the JSON for local development, but production
    deployments should inject the environment value and omit ``apiKey``.
    """

    plugins = [create_model_plugin()]
    raw = settings.model_runtime_pool_json.strip()
    if not raw or raw == "[]":
        return plugins
    value = json.loads(raw)
    if not isinstance(value, list):
        raise ValueError("MODEL_RUNTIME_POOL_JSON must be a JSON array")
    seen = {"default"}
    for entry in value:
        if not isinstance(entry, dict):
            raise ValueError("each model runtime entry must be an object")
        runtime_id = str(entry.get("runtimeId", "")).strip().lower()
        if not runtime_id or runtime_id in seen:
            raise ValueError(f"invalid or duplicate model runtime id: {runtime_id!r}")
        seen.add(runtime_id)
        provider_name = str(entry.get("provider", settings.model_provider))
        provider = _build_provider(
            provider_name=provider_name,
            api_key=str(entry.get("apiKey", settings.model_api_key)),
            base_url=str(entry.get("baseUrl", settings.model_base_url)),
            trust_env=bool(entry.get("trustEnv", settings.model_http_trust_env)),
            input_cost_per_million=_float(entry, "inputCostPerMillion", settings.model_input_cost_per_million),
            output_cost_per_million=_float(entry, "outputCostPerMillion", settings.model_output_cost_per_million),
        )
        gateway = ModelGateway(
            provider,
            timeout=_float(entry, "timeoutSeconds", settings.model_timeout_seconds),
            max_retries=_int(entry, "maxRetries", settings.model_max_retries),
        )
        plugins.append(
            ModelGatewayPlugin(
                gateway,
                str(entry.get("model", settings.model_name)),
                runtime_id=runtime_id,
                vision_model=str(entry.get("visionModel", settings.model_vision_name)),
                routing_quality_score=_float(entry, "qualityScore", 0.8),
                routing_avg_latency_ms=_int(entry, "avgLatencyMs", 1000),
                routing_avg_cost=_float(entry, "avgCost", 0.0),
                routing_success_rate=_float(entry, "successRate", 1.0),
                routing_sample_count=_int(entry, "sampleCount", 0),
            )
        )
    return plugins
