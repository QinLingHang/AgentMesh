from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.kernel import RuntimeContext
from app.models import ModelInputAttachment, ModelMessage, ModelRequest, ModelResponse
from app.models.gateway import ModelEventHandler, ModelGateway
from app.optimization import AdaptiveModelRouter, ModelRouteDecision
from app.models.providers import OpenAICompatibleModelProvider
from app.schemas import AgentProfile, TaskConstraints, TaskProfile, ProjectModelRuntime


class ModelRuntimeResolutionError(RuntimeError):
    """Raised when a model runtime cannot be resolved."""


@dataclass(slots=True)
class ResolvedModelRuntime:
    runtime_id: str
    gateway: Any
    gateway_provider: str
    declared_provider: str
    model: str
    vision_model: str | None
    plugin: Any
    router: AdaptiveModelRouter | None = None
    route_decision: ModelRouteDecision | None = None
    last_response: ModelResponse | None = field(default=None, init=False)

    async def generate(
        self,
        prompt: str,
        on_event: ModelEventHandler | None = None,
        attachments: list[ModelInputAttachment] | None = None,
    ) -> str:
        response = await self.generate_response(prompt, on_event, attachments)
        return response.content

    async def generate_response(
        self,
        prompt: str,
        on_event: ModelEventHandler | None = None,
        attachments: list[ModelInputAttachment] | None = None,
    ) -> ModelResponse:
        selected_model = (
            self.vision_model
            if attachments and self.vision_model
            else self.model
        )
        request = ModelRequest(
            model=selected_model,
            messages=[
                ModelMessage(role="system", content="You are an AgentMesh Runtime execution model."),
                ModelMessage(role="user", content=prompt),
            ],
            temperature=0.2,
            attachments=list(attachments or []),
        )
        try:
            response = await self.gateway.generate(request, on_event)
        except Exception:
            if self.router is not None:
                self.router.performance.record_execution(
                    self.runtime_id,
                    self.plugin,
                    success=False,
                    latency_ms=0,
                    cost=None,
                )
            raise
        self.last_response = response
        if self.router is not None:
            self.router.performance.record_execution(
                self.runtime_id,
                self.plugin,
                success=True,
                latency_ms=response.latency_ms,
                cost=response.estimated_cost,
            )
        return response

    def record_quality(self, quality: float) -> None:
        if self.router is not None:
            self.router.performance.record_quality(
                self.runtime_id,
                self.plugin,
                quality,
            )




def resolve_project_model_runtime(
    project_model: ProjectModelRuntime,
    *,
    require_explicit_vision: bool = False,
) -> ResolvedModelRuntime:
    """Build a request-local BYOK runtime without mutating RuntimeContext.

    Normal task execution keeps the P9-compatible fallback where ``modelName`` may
    also be a multimodal model. Knowledge ingestion can opt into
    ``require_explicit_vision=True`` so image bytes are never silently sent to a
    text-only model when ``visionModelName`` was not configured.
    """
    provider = OpenAICompatibleModelProvider(
        api_key=project_model.api_key.get_secret_value(),
        base_url=project_model.base_url,
        trust_env=False,
    )
    return ResolvedModelRuntime(
        runtime_id="project-byok",
        gateway=ModelGateway(provider, timeout=30.0, max_retries=1),
        gateway_provider=provider.name,
        declared_provider=project_model.provider,
        model=project_model.model_name,
        vision_model=(
            project_model.vision_model_name
            if require_explicit_vision
            else (project_model.vision_model_name or project_model.model_name)
        ),
        plugin=provider,
        router=None,
        route_decision=None,
    )


class ModelRuntimeResolver:
    def __init__(self, context: RuntimeContext) -> None:
        self._context = context
        self.model_router = AdaptiveModelRouter(context)

    def resolve(
        self,
        agent: AgentProfile,
        *,
        adaptive: bool = False,
        constraints: TaskConstraints | None = None,
        profile: TaskProfile | None = None,
        project_model: ProjectModelRuntime | None = None,
    ) -> ResolvedModelRuntime:
        requested_runtime = agent.model_runtime.strip().lower() or "default"
        route_decision: ModelRouteDecision | None = None

        # P9 Project BYOK is request-local. It never mutates RuntimeContext and
        # therefore cannot leak across projects or later requests.
        if project_model is not None:
            return resolve_project_model_runtime(project_model)

        if adaptive and constraints is not None and profile is not None:
            try:
                route_decision = self.model_router.route(
                    preferred_runtime=requested_runtime,
                    profile=profile,
                    constraints=constraints,
                )
                runtime_id = route_decision.selected_runtime_id
            except Exception as exc:
                # Routing must not create a new single point of failure. If the
                # agent/runtime was previously valid, fall back to its declared
                # route and let the normal resolver produce the canonical error
                # when that route is actually unavailable.
                if requested_runtime in {"adaptive", "auto"}:
                    runtime_id = "default"
                else:
                    runtime_id = requested_runtime
                route_decision = None
        else:
            runtime_id = "default" if requested_runtime in {"adaptive", "auto"} else requested_runtime

        service_key = f"model.runtime.{runtime_id}"
        try:
            base_runtime = self._context.get(service_key)
        except KeyError as exc:
            raise ModelRuntimeResolutionError(
                f"model runtime is not registered: {runtime_id}"
            ) from exc

        # Under adaptive routing the runtime owns its model identity. Under a
        # pinned/default legacy route, an Agent-specific modelName override is
        # retained for backward compatibility.
        if route_decision is not None and route_decision.mode == "adaptive":
            model_name = str(base_runtime.model)
            declared_provider = str(base_runtime.provider)
        else:
            model_name = agent.model_name.strip() or base_runtime.model
            declared_provider = agent.provider.strip() or base_runtime.provider

        return ResolvedModelRuntime(
            runtime_id=runtime_id,
            gateway=base_runtime.gateway,
            gateway_provider=base_runtime.provider,
            declared_provider=declared_provider,
            model=model_name,
            vision_model=(
                str(getattr(base_runtime, "vision_model", "")).strip()
                or None
            ),
            plugin=base_runtime,
            router=self.model_router if adaptive else None,
            route_decision=route_decision,
        )
