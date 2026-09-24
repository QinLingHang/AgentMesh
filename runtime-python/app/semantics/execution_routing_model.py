"""Bounded model assistance for Execution Routing task understanding.

The model may describe intent, but never grants or selects resource IDs.  It is
used only when deterministic analysis is indeterminate/complex, and only with
the request's already-authorized model runtime.  Failure is fail-closed: the
caller keeps the deterministic result.
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.config import settings


class SemanticIntentDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective: str = Field(min_length=1, max_length=600)
    capability_kinds: list[Literal["KNOWLEDGE", "TOOL", "MCP", "AGENT"]] = Field(
        default_factory=list, max_length=4, alias="capabilityKinds"
    )
    knowledge_dependency: Literal["NONE", "OPTIONAL", "REQUIRED"] = Field(
        default="NONE", alias="knowledgeDependency"
    )
    multi_step: bool = Field(default=False, alias="multiStep")
    has_dependencies: bool = Field(default=False, alias="hasDependencies")
    has_conditional_effects: bool = Field(default=False, alias="hasConditionalEffects")
    requested_effects: list[Literal["READ", "WRITE", "EXECUTE", "EXTERNAL_SEND"]] = Field(
        default_factory=list, max_length=4, alias="requestedEffects"
    )
    unknowns: list[str] = Field(default_factory=list, max_length=4)
    reason_codes: list[str] = Field(default_factory=list, max_length=8, alias="reasonCodes")


_COMPLEX_CUES = (
    "如果", "若", "否则", "直到", "分别", "同时", "根据结果", "发现问题", "检查后",
    "if ", "unless", "otherwise", "depending on", "based on the result", "respectively",
)


def should_use_semantic_routing_model(req, baseline) -> bool:
    from app.semantics.execution_routing import needs_semantic_routing_model
    return settings.execution_routing_semantic_model_enabled and needs_semantic_routing_model(req, baseline)


def _extract_json(text: str) -> dict:
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I)
        raw = re.sub(r"\s*```$", "", raw)
    # Reject prose concatenated with a JSON object. Structured model output
    # cannot smuggle an alternative instruction outside the validated schema.
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("semantic model must return exactly one JSON object")
    return parsed


async def describe_routing_with_model(engine, req) -> tuple[SemanticIntentDescriptor, dict[str, object]] | None:
    """Return a descriptive intent only; no resource names/IDs are sent or accepted."""
    if engine is None:
        return None
    if not req.model_pool and req.project_model is None:
        # No request-authorized model configuration. Never silently consume a
        # different third-party account just for routing.
        return None
    from app.schemas import AgentProfile
    from app.services.profiler import profile_task
    agent = AgentProfile(
        id=0,
        name="ExecutionRouteInterpreter",
        endpoint="internal://routing-intent",
        protocol="internal",
        capabilities=["execution_routing"],
        modelRuntime="adaptive",
    )
    try:
        runtime = engine.model_runtime_resolver.resolve(
            agent,
            adaptive=False,
            constraints=req.constraints,
            profile=profile_task(req.task),
            project_model=req.project_model,
            model_pool=req.model_pool,
            model_selection=req.model_selection,
        )
    except Exception:
        return None
    prompt = (
        "You classify the user's requested outcome for a governed Agent platform. "
        "Return exactly one JSON object and nothing else. Never invent resource IDs, tool names, "
        "knowledge-base names, permissions, task IDs, files, or prior history. If a critical target "
        "is missing, put a short description in unknowns. capabilityKinds can only contain "
        "KNOWLEDGE, TOOL, MCP, AGENT. KNOWLEDGE means tenant/project-specific policy or factual "
        "content; TOOL means live personal/business data or an operation; MCP means explicitly "
        "requested MCP; AGENT means explicit delegation to an Agent. General explanations need none. "
        "requestedEffects can only contain READ, WRITE, EXECUTE, EXTERNAL_SEND.\n"
        "Schema: {\"objective\":\"...\",\"capabilityKinds\":[],\"knowledgeDependency\":"
        "\"NONE|OPTIONAL|REQUIRED\",\"multiStep\":false,\"hasDependencies\":false,"
        "\"hasConditionalEffects\":false,\"requestedEffects\":[],\"unknowns\":[],"
        "\"reasonCodes\":[]}\n"
        f"USER_REQUEST:\n{req.task[:12000]}"
    )
    try:
        response = await asyncio.wait_for(
            runtime.generate_response(prompt),
            timeout=max(0.2, float(settings.execution_routing_semantic_model_timeout_seconds)),
        )
        descriptor = SemanticIntentDescriptor.model_validate(_extract_json(response.content))
    except Exception:
        return None
    # Reason codes are diagnostic enums only. Free-form model prose must never
    # flow into production routing trace.
    descriptor.reason_codes = [
        code for code in descriptor.reason_codes
        if re.fullmatch(r"[A-Z0-9_]{1,64}", code or "")
    ][:8]
    # Usage metadata differs across providers; unknown cost must be reported
    # as unknown rather than silently claiming a zero-cost model call.
    import math
    try:
        tokens = max(0, int(getattr(response, "total_tokens", None) or 0))
    except (TypeError, ValueError, OverflowError):
        tokens = 0
    estimated = getattr(response, "estimated_cost", None)
    try:
        cost = float(estimated) if estimated is not None else 0.0
        known = estimated is not None and math.isfinite(cost) and cost >= 0
    except (TypeError, ValueError, OverflowError):
        known, cost = False, 0.0
    if not known:
        cost = 0.0
    return descriptor, {
        "model_calls": 1,
        "model_tokens": tokens,
        "model_estimated_cost": cost,
        "model_cost_known": known,
    }
