from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.config import settings
from app.kernel import RuntimeContext
from app.models import ModelInputAttachment, ModelMessage, ModelRequest, ModelResponse
from app.models.gateway import ModelEventHandler, ModelGateway
from app.optimization import AdaptiveModelRouter, ModelRouteDecision
from app.models.providers import MockModelProvider, OpenAICompatibleModelProvider
from app.schemas import AgentProfile, ModelSelection, TaskConstraints, TaskProfile, ProjectModelRuntime


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
    service_id: int | None = None
    service_name: str | None = None
    selection_mode: str = "declared"
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

    async def generate_stream(
        self,
        prompt: str,
        on_event: ModelEventHandler | None = None,
        on_delta: Any = None,
    ) -> str:
        request = ModelRequest(
            model=self.model,
            messages=[
                ModelMessage(role="system", content="You are an AgentMesh Runtime execution model."),
                ModelMessage(role="user", content=prompt),
            ],
            temperature=0.2,
        )
        try:
            response = await self.gateway.generate_stream(request, on_event, on_delta)
        except Exception:
            if self.router is not None:
                self.router.performance.record_execution(
                    self.runtime_id, self.plugin, success=False, latency_ms=0, cost=None,
                )
            raise
        self.last_response = response
        if self.router is not None:
            self.router.performance.record_execution(
                self.runtime_id, self.plugin, success=True,
                latency_ms=response.latency_ms, cost=response.estimated_cost,
            )
        return response.content

    def record_quality(self, quality: float) -> None:
        if self.router is not None:
            self.router.performance.record_quality(
                self.runtime_id,
                self.plugin,
                quality,
            )



def _request_local_provider(item: ProjectModelRuntime):
    normalized = item.provider.strip().lower().replace("_", "-")
    if normalized == "mock":
        return MockModelProvider()
    return OpenAICompatibleModelProvider(
        api_key=item.api_key.get_secret_value(),
        base_url=item.base_url,
        trust_env=False,
        # Request-local BYOK previously bypassed the runtime pricing settings,
        # so browser-selected qwen-plus calls always reported cost as unknown
        # even when operators configured pricing. Pricing remains opt-in and
        # account-specific; zero still means unknown rather than a fabricated
        # zero-cost call.
        input_cost_per_million=settings.model_input_cost_per_million,
        output_cost_per_million=settings.model_output_cost_per_million,
    )


@dataclass(slots=True)
class RequestLocalModelCandidate:
    runtime_id: str
    gateway: ModelGateway
    provider: str
    model: str
    vision_model: str | None
    service_id: int | None
    service_name: str | None
    routing_is_default: bool = False
    routing_quality_score: float = 0.8
    routing_avg_latency_ms: int = 1000
    routing_avg_cost: float = 0.0
    routing_success_rate: float = 1.0
    routing_sample_count: int = 0


def _request_local_candidate(item: ProjectModelRuntime) -> RequestLocalModelCandidate:
    provider = _request_local_provider(item)
    runtime_id = f"user-service-{item.service_id}" if item.service_id else "request-byok"
    return RequestLocalModelCandidate(
        runtime_id=runtime_id,
        gateway=ModelGateway(provider, timeout=30.0, max_retries=1),
        provider=item.provider,
        model=item.model_name,
        vision_model=(item.vision_model_name or "").strip() or None,
        service_id=item.service_id,
        service_name=item.service_name,
        routing_is_default=item.is_default,
    )


def resolve_project_model_runtime(
    project_model: ProjectModelRuntime,
    *,
    require_explicit_vision: bool = False,
) -> ResolvedModelRuntime:
    """Build a request-local BYOK runtime without mutating RuntimeContext.

    Normal task execution keeps the governance-compatible fallback where ``modelName`` may
    also be a multimodal model. Knowledge ingestion can opt into
    ``require_explicit_vision=True`` so image bytes are never silently sent to a
    text-only model when ``visionModelName`` was not configured.
    """
    provider = _request_local_provider(project_model)
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
        model_pool: list[ProjectModelRuntime] | None = None,
        model_selection: ModelSelection | None = None,
        has_images: bool = False,
    ) -> ResolvedModelRuntime:
        requested_runtime = agent.model_runtime.strip().lower() or "default"
        route_decision: ModelRouteDecision | None = None
        selection = model_selection or ModelSelection()

        # Personal BYOK model services are request-local and take precedence over
        # the shared Project fallback. The pool never mutates RuntimeContext.
        if model_pool:
            candidates = [_request_local_candidate(item) for item in model_pool]
            if has_images:
                visual = [item for item in candidates if item.vision_model]
                if not visual:
                    raise ModelRuntimeResolutionError(
                        "the selected model service does not provide a vision model"
                    )
                candidates = visual

            by_id = {item.runtime_id: item for item in candidates}
            if selection.mode == "manual":
                if selection.service_id is None:
                    raise ModelRuntimeResolutionError("manual model selection requires serviceId")
                runtime_id = f"user-service-{selection.service_id}"
                if runtime_id not in by_id:
                    raise ModelRuntimeResolutionError("selected model service is unavailable")
                if constraints is not None and profile is not None:
                    route_decision = self.model_router.route_candidates(
                        runtimes=[(runtime_id, by_id[runtime_id])],
                        preferred_runtime=runtime_id,
                        profile=profile,
                        constraints=constraints,
                    )
            else:
                if constraints is None or profile is None:
                    # The caller normally supplies both. A deterministic default
                    # keeps request-local BYOK usable in isolated tests.
                    chosen = next((item for item in candidates if item.routing_is_default), candidates[0])
                    runtime_id = chosen.runtime_id
                else:
                    route_decision = self.model_router.route_candidates(
                        runtimes=[(item.runtime_id, item) for item in candidates],
                        preferred_runtime="adaptive",
                        profile=profile,
                        constraints=constraints,
                    )
                    runtime_id = route_decision.selected_runtime_id

            selected = by_id[runtime_id]
            return ResolvedModelRuntime(
                runtime_id=runtime_id,
                gateway=selected.gateway,
                gateway_provider=selected.gateway.provider.name,
                declared_provider=selected.provider,
                model=selected.model,
                vision_model=selected.vision_model,
                plugin=selected,
                service_id=selected.service_id,
                service_name=selected.service_name,
                selection_mode=selection.mode,
                router=self.model_router,
                route_decision=route_decision,
            )

        # Project BYOK is request-local. It never mutates RuntimeContext and
        # therefore cannot leak across projects or later requests.
        if project_model is not None:
            resolved = resolve_project_model_runtime(project_model)
            resolved.selection_mode = "project_fallback"
            return resolved

        if adaptive and constraints is not None and profile is not None:
            try:
                route_decision = self.model_router.route(
                    preferred_runtime=requested_runtime,
                    profile=profile,
                    constraints=constraints,
                )
                runtime_id = route_decision.selected_runtime_id
            except Exception:
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
            selection_mode=(route_decision.mode if route_decision is not None else "declared"),
            router=self.model_router if adaptive else None,
            route_decision=route_decision,
        )
