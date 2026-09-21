"""Narrow compatibility layer for the pinned OpenJiuwen SDK.

The rest of AgentMesh must not depend on OpenJiuwen classes directly.  This
module owns the SDK imports, model-client registration, Tool/Card projection,
Session lifecycle and Runner invocation.  It is intentionally request-scoped
around the platform's existing model and tool boundaries:

* SDK model calls are translated to ``ModelGateway`` requests.
* SDK tools call ``OpenJiuwenToolBridge`` and never call an adapter directly.
* every invocation receives a tenant-qualified, one-shot SDK Session.
"""

from __future__ import annotations

import asyncio
import contextvars
import hashlib
import importlib
import inspect
import json
import logging
import time
import uuid

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from app.agents.contracts import AgentExecutionRequest, AgentExecutionResult
from app.config import settings
from app.models.contracts import (
    ModelInputAttachment,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelTool,
    ToolCall,
)
from app.tools.approval import ToolApprovalRequest, ToolApprovalRequired


logger = logging.getLogger(__name__)


class OpenJiuwenSdkAdapterError(RuntimeError):
    """The pinned SDK cannot be adapted to the AgentMesh contracts."""


class OpenJiuwenSdkDeadlineError(TimeoutError):
    """An SDK execution exceeded its AgentMesh deadline."""


_adapter_context: contextvars.ContextVar[Any | None] = contextvars.ContextVar(
    "agentmesh_openjiuwen_model_adapter",
    default=None,
)
_client_classes: dict[type, type] = {}


def _sdk_module(sdk: Any, name: str) -> Any:
    """Import an SDK module, with a small attribute fallback for test doubles."""

    try:
        return importlib.import_module(name)
    except Exception as exc:
        # A real pinned installation always imports through the normal path.
        # The fallback keeps the adapter unit-testable with a module-shaped SDK
        # double while still reporting a useful error when neither path works.
        current = getattr(sdk, "module", None)
        for part in name.split(".")[1:]:
            current = getattr(current, part, None)
            if current is None:
                raise OpenJiuwenSdkAdapterError(
                    f"OpenJiuwen SDK module {name!r} is unavailable: {exc}"
                ) from exc
        return current


def _sdk_attr(module: Any, module_name: str, name: str) -> Any:
    """Resolve a required SDK symbol with an actionable compatibility error."""

    value = getattr(module, name, None)
    if value is None:
        raise OpenJiuwenSdkAdapterError(
            f"OpenJiuwen SDK API {module_name}.{name} is unavailable; "
            "the pinned SDK is incompatible with the AgentMesh adapter"
        )
    return value


def _sdk_types(sdk: Any) -> dict[str, Any]:
    llm = _sdk_module(sdk, "openjiuwen.core.foundation.llm")
    base_client = _sdk_module(
        sdk,
        "openjiuwen.core.foundation.llm.model_clients.base_model_client",
    )
    tool = _sdk_module(sdk, "openjiuwen.core.foundation.tool")
    single_agent = _sdk_module(sdk, "openjiuwen.core.single_agent")
    message = _sdk_module(
        sdk,
        "openjiuwen.core.foundation.llm.schema.message",
    )
    message_chunk = _sdk_module(
        sdk,
        "openjiuwen.core.foundation.llm.schema.message_chunk",
    )
    tool_call = _sdk_module(
        sdk,
        "openjiuwen.core.foundation.llm.schema.tool_call",
    )
    config = _sdk_module(
        sdk,
        "openjiuwen.core.foundation.llm.schema.config",
    )
    generation = _sdk_module(
        sdk,
        "openjiuwen.core.foundation.llm.schema.generation_response",
    )
    return {
        "Model": _sdk_attr(llm, "openjiuwen.core.foundation.llm", "Model"),
        "BaseModelClient": _sdk_attr(
            base_client,
            "openjiuwen.core.foundation.llm.model_clients.base_model_client",
            "BaseModelClient",
        ),
        "Tool": _sdk_attr(tool, "openjiuwen.core.foundation.tool", "Tool"),
        "ToolCard": _sdk_attr(tool, "openjiuwen.core.foundation.tool", "ToolCard"),
        "ToolInfo": _sdk_attr(tool, "openjiuwen.core.foundation.tool", "ToolInfo"),
        "AgentCard": _sdk_attr(single_agent, "openjiuwen.core.single_agent", "AgentCard"),
        "ReActAgent": _sdk_attr(single_agent, "openjiuwen.core.single_agent", "ReActAgent"),
        "ReActAgentConfig": _sdk_attr(
            single_agent,
            "openjiuwen.core.single_agent",
            "ReActAgentConfig",
        ),
        "create_agent_session": _sdk_attr(
            single_agent,
            "openjiuwen.core.single_agent",
            "create_agent_session",
        ),
        "AssistantMessage": _sdk_attr(
            message,
            "openjiuwen.core.foundation.llm.schema.message",
            "AssistantMessage",
        ),
        "AssistantMessageChunk": _sdk_attr(
            message_chunk,
            "openjiuwen.core.foundation.llm.schema.message_chunk",
            "AssistantMessageChunk",
        ),
        "ToolMessage": getattr(message, "ToolMessage", None),
        "UsageMetadata": getattr(message, "UsageMetadata", None),
        "ToolCall": _sdk_attr(
            tool_call,
            "openjiuwen.core.foundation.llm.schema.tool_call",
            "ToolCall",
        ),
        "ModelClientConfig": _sdk_attr(
            config,
            "openjiuwen.core.foundation.llm.schema.config",
            "ModelClientConfig",
        ),
        "ModelRequestConfig": _sdk_attr(
            config,
            "openjiuwen.core.foundation.llm.schema.config",
            "ModelRequestConfig",
        ),
        # Media response classes are retained for future gateway extensions;
        # text-agent execution does not require them to be present.
        "ImageGenerationResponse": getattr(generation, "ImageGenerationResponse", None),
        "AudioGenerationResponse": getattr(generation, "AudioGenerationResponse", None),
        "VideoGenerationResponse": getattr(generation, "VideoGenerationResponse", None),
    }


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    if isinstance(content, (list, tuple)):
        return "".join(_content_to_text(item) for item in content)
    if isinstance(content, dict):
        for key in ("text", "content"):
            if key in content:
                return _content_to_text(content[key])
    for attribute in ("text", "content"):
        nested = getattr(content, attribute, None)
        if nested is not None and nested is not content:
            return _content_to_text(nested)
    try:
        return json.dumps(content, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(content)


def _sdk_messages_to_mesh(messages: Any) -> list[ModelMessage]:
    if isinstance(messages, str):
        messages = [{"role": "user", "content": messages}]
    result: list[ModelMessage] = []
    for message in list(messages or []):
        raw_role = getattr(message, "role", None)
        if raw_role is None and isinstance(message, dict):
            raw_role = message.get("role", "user")
        raw_role = getattr(raw_role, "value", raw_role) or "user"
        role = str(raw_role).lower()
        if role not in {"system", "user", "assistant", "tool"}:
            role = "user"
        content = getattr(message, "content", None)
        if content is None and isinstance(message, dict):
            content = message.get("content", "")
        calls: list[ToolCall] = []
        raw_calls = getattr(message, "tool_calls", None)
        if raw_calls is None and isinstance(message, dict):
            raw_calls = message.get("tool_calls")
        for index, call in enumerate(raw_calls or []):
            name = getattr(call, "name", None)
            arguments = getattr(call, "arguments", None)
            call_id = getattr(call, "id", None)
            function = getattr(call, "function", None)
            if function is not None:
                name = name or getattr(function, "name", None)
                arguments = arguments if arguments is not None else getattr(
                    function,
                    "arguments",
                    None,
                )
            if isinstance(call, dict):
                function = call.get("function") or {}
                name = name or call.get("name") or function.get("name")
                arguments = arguments if arguments is not None else call.get("arguments")
                arguments = arguments if arguments is not None else function.get("arguments")
                call_id = call_id or call.get("id")
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments or "{}")
                except (TypeError, ValueError):
                    arguments = {}
            if not isinstance(arguments, dict):
                arguments = {}
            calls.append(
                ToolCall(
                    id=str(call_id or f"sdk_call_{index}"),
                    name=str(name or ""),
                    arguments=arguments,
                )
            )
        result.append(
            ModelMessage(
                role=role,
                content=_content_to_text(content),
                tool_call_id=(
                    getattr(message, "tool_call_id", None)
                    or (message.get("tool_call_id") if isinstance(message, dict) else None)
                ),
                tool_calls=calls,
            )
        )
    return result


def _sdk_tools_to_mesh(tools: Any) -> list[ModelTool]:
    result: list[ModelTool] = []
    for tool in list(tools or []):
        if isinstance(tool, dict):
            name = tool.get("name", "")
            description = tool.get("description", "")
            schema = (
                tool.get("parameters")
                or tool.get("input_schema")
                or tool.get("input_params")
                or {}
            )
        else:
            name = getattr(tool, "name", "") or getattr(tool, "tool_name", "")
            description = getattr(tool, "description", "") or getattr(
                tool,
                "desc",
                "",
            )
            schema = (
                getattr(tool, "parameters", None)
                or getattr(tool, "input_schema", None)
                or getattr(tool, "input_params", None)
            )
        if hasattr(schema, "model_dump"):
            schema = schema.model_dump()
        if not isinstance(schema, dict):
            schema = {}
        result.append(
            ModelTool(
                name=str(name),
                description=str(description or ""),
                input_schema=schema,
            )
        )
    return result


def _usage_metadata(types: dict[str, Any], response: ModelResponse) -> Any:
    usage_type = types.get("UsageMetadata")
    if usage_type is None:
        return None
    return usage_type(
        input_tokens=int(response.input_tokens or 0),
        output_tokens=int(response.output_tokens or 0),
        total_tokens=int(response.total_tokens or 0),
        total_latency=float(response.latency_ms or 0) / 1000.0,
        model_name=response.model,
        input_cost=float(response.estimated_cost or 0.0),
        total_cost=float(response.estimated_cost or 0.0),
    )


def _mesh_to_sdk_message(types: dict[str, Any], response: ModelResponse) -> Any:
    calls = [
        types["ToolCall"](
            id=call.id,
            type="function",
            name=call.name,
            arguments=json.dumps(call.arguments, ensure_ascii=False),
        )
        for call in response.tool_calls
    ]
    return types["AssistantMessage"](
        content=response.content or "",
        tool_calls=calls or [],
        usage_metadata=_usage_metadata(types, response),
        finish_reason=response.finish_reason or "stop",
        response_model=response.model,
        metadata={
            "agentmesh_provider": response.provider,
            "agentmesh_total_tokens": response.total_tokens,
        },
    )


def _stream_item_to_sdk_chunk(
    types: dict[str, Any],
    item: dict[str, Any],
) -> Any:
    raw_kind = item.get("type", "delta")
    kind = str(getattr(raw_kind, "value", raw_kind))
    content = str(item.get("delta", "") or "") if kind == "delta" else ""
    raw_calls = item.get("tool_calls") or []
    calls = []
    for index, call in enumerate(raw_calls):
        if isinstance(call, dict):
            function = call.get("function") or {}
            name = call.get("name") or function.get("name") or ""
            arguments = call.get("arguments")
            arguments = arguments if arguments is not None else function.get("arguments", "")
            call_id = call.get("id")
        else:
            name = getattr(call, "name", "")
            arguments = getattr(call, "arguments", "")
            call_id = getattr(call, "id", None)
        if isinstance(arguments, dict):
            arguments = json.dumps(arguments, ensure_ascii=False)
        calls.append(
            types["ToolCall"](
                id=str(call_id or f"sdk_stream_call_{index}"),
                type="function",
                name=str(name),
                arguments=str(arguments or ""),
            )
        )
    usage = None
    if kind == "done":
        usage = types.get("UsageMetadata")
        if usage is not None:
            usage = usage(
                input_tokens=int(item.get("input_tokens", 0) or 0),
                output_tokens=int(item.get("output_tokens", 0) or 0),
                total_tokens=int(item.get("total_tokens", 0) or 0),
                total_latency=float(item.get("latency_ms", 0) or 0) / 1000.0,
                model_name=str(item.get("model", "") or ""),
                total_cost=float(item.get("estimated_cost", 0.0) or 0.0),
            )
    return types["AssistantMessageChunk"](
        content=content,
        tool_calls=calls or None,
        usage_metadata=usage,
        finish_reason=(item.get("finish_reason") or "stop") if kind == "done" else "null",
    )


def _ensure_model_client_class(sdk: Any, types: dict[str, Any]) -> type:
    base = types["BaseModelClient"]
    cached = _client_classes.get(base)
    if cached is not None:
        return cached

    adapter_name = "agentmesh_gateway"

    class AgentMeshGatewayModelClient(base):
        __client_name__ = adapter_name
        __client_type__ = "llm"

        def __init__(self, model_config: Any, model_client_config: Any):
            super().__init__(model_config, model_client_config)
            adapter = _adapter_context.get()
            if adapter is None:
                raise OpenJiuwenSdkAdapterError(
                    "AgentMesh OpenJiuwen model client was constructed outside "
                    "an execution adapter context"
                )
            self._adapter = adapter

        async def invoke(self, messages, *, tools=None, temperature=None, top_p=None,
                         model=None, max_tokens=None, stop=None, output_parser=None,
                         timeout=None, **kwargs):
            response = await self._adapter.generate(
                _sdk_messages_to_mesh(messages),
                _sdk_tools_to_mesh(tools),
                timeout_override=timeout,
                temperature=temperature,
                top_p=top_p,
                max_tokens=max_tokens,
                stop=stop,
                model=model,
            )
            return _mesh_to_sdk_message(types, response)

        async def stream(self, messages, *, tools=None, temperature=None, top_p=None,
                         model=None, max_tokens=None, stop=None, output_parser=None,
                         timeout=None, **kwargs):
            async for item in self._adapter.stream(
                _sdk_messages_to_mesh(messages),
                _sdk_tools_to_mesh(tools),
                timeout_override=timeout,
                temperature=temperature,
                top_p=top_p,
                max_tokens=max_tokens,
                stop=stop,
                model=model,
            ):
                yield _stream_item_to_sdk_chunk(types, item)

        async def generate_image(self, messages, **kwargs):
            raise NotImplementedError("AgentMesh Gateway does not expose image generation through OpenJiuwen")

        async def generate_speech(self, messages, **kwargs):
            raise NotImplementedError("AgentMesh Gateway does not expose speech generation through OpenJiuwen")

        async def generate_video(self, messages, **kwargs):
            raise NotImplementedError("AgentMesh Gateway does not expose video generation through OpenJiuwen")

    _client_classes[base] = AgentMeshGatewayModelClient
    return AgentMeshGatewayModelClient


class OpenJiuwenModelAdapter:
    """Translate OpenJiuwen model calls into AgentMesh ModelGateway calls."""

    def __init__(
        self,
        model_runtime: Any,
        *,
        attachments: list[ModelInputAttachment] | None = None,
        on_model_event: Any = None,
        deadline_at: float | None = None,
        cancel_event: asyncio.Event | None = None,
        session_id: str = "",
    ) -> None:
        self.model_runtime = model_runtime
        self.attachments = list(attachments or [])
        self.on_model_event = on_model_event
        self.deadline_at = deadline_at
        self.cancel_event = cancel_event
        self.session_id = session_id
        self.model_calls = 0
        self.stream_calls = 0

    @property
    def model_name(self) -> str:
        return (
            settings.openjiuwen_model_name
            or getattr(self.model_runtime, "model", "")
            or "default"
        )

    def _remaining_timeout(self, override: float | None = None) -> float:
        values = [value for value in (override, getattr(settings, "model_timeout_seconds", None)) if value]
        timeout = float(values[0] if values else 60.0)
        if self.deadline_at is not None:
            remaining = self.deadline_at - time.monotonic()
            if remaining <= 0:
                raise OpenJiuwenSdkDeadlineError("OPENJIUWEN_DEADLINE_EXCEEDED")
            timeout = min(timeout, remaining)
        # Do not round a request up after its deadline.  ModelRequest validates
        # this field as strictly positive, so preserve the tiny positive
        # remainder instead of adding an arbitrary grace period.
        if timeout <= 0:
            raise OpenJiuwenSdkDeadlineError("OPENJIUWEN_DEADLINE_EXCEEDED")
        return timeout

    def _check_control(self) -> None:
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise asyncio.CancelledError
        if self.deadline_at is not None and time.monotonic() >= self.deadline_at:
            raise OpenJiuwenSdkDeadlineError("OPENJIUWEN_DEADLINE_EXCEEDED")

    def _event(
        self,
        payload: dict[str, Any],
        handler: Any = None,
    ) -> None:
        callback = self.on_model_event if handler is None else handler
        if callback is None:
            return
        event = dict(payload)
        event.setdefault("executorType", "openjiuwen")
        if self.session_id:
            event.setdefault("sessionId", self.session_id)
        callback(event)

    def _request(
        self,
        messages: list[ModelMessage],
        tools: list[ModelTool],
        *,
        timeout_override: float | None = None,
        temperature: float | None = 0.2,
        max_tokens: int | None = None,
        model: str | None = None,
        **_: Any,
    ) -> ModelRequest:
        selected_model = model
        if not selected_model and self.attachments:
            selected_model = getattr(self.model_runtime, "vision_model", None)
        return ModelRequest(
            model=selected_model or self.model_name,
            messages=messages,
            tools=tools or [],
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=self._remaining_timeout(timeout_override),
            attachments=list(self.attachments),
        )

    async def _await_gateway(self, awaitable: Any, timeout: float) -> Any:
        task = asyncio.create_task(awaitable)
        cancel_task = None
        wait_set: set[asyncio.Task[Any]] = {task}
        if self.cancel_event is not None:
            cancel_task = asyncio.create_task(self.cancel_event.wait())
            wait_set.add(cancel_task)
        try:
            done, _ = await asyncio.wait(wait_set, timeout=timeout)
            # Cancellation wins ties with a completed gateway task.  This
            # keeps a caller-requested stop from being reported as success
            # merely because both tasks became ready in the same loop turn.
            if cancel_task is not None and cancel_task in done and self.cancel_event.is_set():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                raise asyncio.CancelledError
            if task not in done:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                raise OpenJiuwenSdkDeadlineError("OPENJIUWEN_DEADLINE_EXCEEDED")
            return await task
        finally:
            if cancel_task is not None and not cancel_task.done():
                cancel_task.cancel()
                await asyncio.gather(cancel_task, return_exceptions=True)

    async def generate(
        self,
        messages: list[ModelMessage],
        tools: list[ModelTool],
        on_model_event: Any = None,
        *,
        timeout_override: float | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        self._check_control()
        request = self._request(messages, tools, timeout_override=timeout_override, **kwargs)
        self.model_calls += 1
        response = await self._await_gateway(
            self.model_runtime.gateway.generate(
                request,
                self._event if on_model_event is None
                else lambda payload: self._event(payload, on_model_event),
            ),
            request.timeout or 60.0,
        )
        self._check_control()
        return response

    async def stream(
        self,
        messages: list[ModelMessage],
        tools: list[ModelTool],
        on_model_event: Any = None,
        *,
        timeout_override: float | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        self._check_control()
        request = self._request(messages, tools, timeout_override=timeout_override, **kwargs)
        self.stream_calls += 1
        stream = self.model_runtime.gateway.stream(
            request,
            self._event if on_model_event is None
            else lambda payload: self._event(payload, on_model_event),
        )
        try:
            async with asyncio.timeout(request.timeout or 60.0):
                if inspect.isawaitable(stream):
                    stream = await stream
                iterator = stream.__aiter__()
                while True:
                    next_task = asyncio.create_task(iterator.__anext__())
                    cancel_task = (
                        asyncio.create_task(self.cancel_event.wait())
                        if self.cancel_event is not None
                        else None
                    )
                    try:
                        if cancel_task is None:
                            item = await next_task
                        else:
                            done, _ = await asyncio.wait(
                                {next_task, cancel_task},
                                return_when=asyncio.FIRST_COMPLETED,
                            )
                            if cancel_task in done and self.cancel_event.is_set():
                                next_task.cancel()
                                await asyncio.gather(
                                    next_task,
                                    return_exceptions=True,
                                )
                                raise asyncio.CancelledError
                            item = await next_task
                    finally:
                        if cancel_task is not None and not cancel_task.done():
                            cancel_task.cancel()
                            await asyncio.gather(
                                cancel_task,
                                return_exceptions=True,
                            )
                        if not next_task.done():
                            next_task.cancel()
                            await asyncio.gather(
                                next_task,
                                return_exceptions=True,
                            )
                    self._check_control()
                    yield item
        except StopAsyncIteration:
            return
        except asyncio.TimeoutError as exc:
            raise OpenJiuwenSdkDeadlineError("OPENJIUWEN_DEADLINE_EXCEEDED") from exc
        finally:
            close = getattr(stream, "aclose", None)
            if callable(close):
                try:
                    await close()
                except asyncio.CancelledError:
                    pass
                except Exception:
                    logger.warning(
                        "OpenJiuwen model stream close failed for session %s",
                        self.session_id or "<unknown>",
                        exc_info=True,
                    )

    def build_sdk_model(self, sdk: Any) -> Any:
        types = _sdk_types(sdk)
        client_class = _ensure_model_client_class(sdk, types)
        model_config = types["ModelRequestConfig"](
            model=self.model_name,
            temperature=0.2,
        )
        client_config = types["ModelClientConfig"](
            client_provider=client_class.__client_name__,
            api_key="agentmesh-gateway",
            api_base="http://agentmesh-gateway.invalid",
            auth_mode="none",
            verify_ssl=False,
            timeout=self._remaining_timeout(),
            stream_first_chunk_timeout=self._remaining_timeout(),
            stream_idle_timeout=self._remaining_timeout(),
        )
        token = _adapter_context.set(self)
        try:
            return types["Model"](
                model_client_config=client_config,
                model_config=model_config,
            )
        finally:
            _adapter_context.reset(token)


def _tenant_hash(scope: str) -> str:
    normalized = scope.strip() or "unscoped"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]


def _sdk_version(sdk: Any) -> str:
    """Read the validated SDK version, including lightweight test doubles."""

    version = getattr(sdk, "version", None)
    if version:
        return str(version)
    module = getattr(sdk, "module", None)
    return str(getattr(module, "__version__", "") or "")


def _new_session_id(request: AgentExecutionRequest) -> str:
    # Never reuse a caller's raw request id as a cross-tenant SDK key. The
    # tenant hash is stable for diagnostics; the nonce makes every execution
    # isolated even when the control plane retries a request id.
    return "am-" + _tenant_hash(request.tenant_scope or f"agent:{request.agent.id}") + "-" + uuid.uuid4().hex


def _remaining_deadline(request: AgentExecutionRequest) -> float | None:
    if request.deadline_at is None:
        return None
    remaining = request.deadline_at - time.monotonic()
    if remaining <= 0:
        raise OpenJiuwenSdkDeadlineError("OPENJIUWEN_DEADLINE_EXCEEDED")
    return remaining


async def _await_with_controls(
    awaitable: Any,
    request: AgentExecutionRequest,
) -> Any:
    remaining = _remaining_deadline(request)
    if remaining is None and request.cancel_event is None:
        return await awaitable
    task = asyncio.create_task(awaitable)
    cancel_task = (
        asyncio.create_task(request.cancel_event.wait())
        if request.cancel_event is not None
        else None
    )
    wait_set: set[asyncio.Task[Any]] = {task}
    if cancel_task is not None:
        wait_set.add(cancel_task)
    try:
        done, _ = await asyncio.wait(wait_set, timeout=remaining)
        if cancel_task is not None and cancel_task in done and request.cancel_event.is_set():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise asyncio.CancelledError
        if task not in done:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise OpenJiuwenSdkDeadlineError("OPENJIUWEN_DEADLINE_EXCEEDED")
        return await task
    finally:
        if cancel_task is not None and not cancel_task.done():
            cancel_task.cancel()
            await asyncio.gather(cancel_task, return_exceptions=True)


def _stream_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "model_dump"):
        try:
            dumped = value.model_dump()
            if isinstance(dumped, dict):
                if "type" in dumped:
                    dumped["type"] = getattr(
                        dumped["type"],
                        "value",
                        dumped["type"],
                    )
                return dumped
        except Exception:
            pass
    payload = getattr(value, "payload", None)
    if isinstance(payload, dict):
        result = {
            "type": getattr(value, "type", "message"),
            "index": getattr(value, "index", 0),
            "payload": payload,
        }
        return result
    return {"type": "message", "payload": {"content": str(value)}}


def _text_from_stream_payload(payload: dict[str, Any]) -> str:
    body = payload.get("payload") if isinstance(payload.get("payload"), dict) else payload
    if not isinstance(body, dict):
        return ""
    for key in ("content", "output", "text"):
        value = body.get(key)
        if isinstance(value, str):
            return value
    return ""


def _result_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("output", "content", "answer", "text"):
            if isinstance(value.get(key), str):
                return value[key]
        payload = value.get("payload")
        if isinstance(payload, dict):
            return _result_text(payload)
        return json.dumps(value, ensure_ascii=False, default=str)
    if hasattr(value, "model_dump"):
        return _result_text(value.model_dump())
    output = getattr(value, "output", None)
    if output is not None:
        return _result_text(output)
    return str(value)


def _context_sections(task: str) -> list[str]:
    sections: list[str] = []
    for line in task.splitlines():
        value = line.strip()
        if value.startswith("[") and value.endswith("]") and len(value) <= 100:
            sections.append(value[1:-1])
    return list(dict.fromkeys(sections))


def _approval_metadata(approval: ToolApprovalRequest) -> dict[str, Any]:
    """Serialize the platform approval envelope into SDK interrupt metadata."""

    return {
        "approvalId": approval.approval_id,
        "toolName": approval.tool_name,
        "protocol": approval.protocol,
        "riskLevel": approval.risk_level,
        "requiresConfirmation": approval.requires_confirmation,
        "arguments": dict(approval.arguments),
        "fingerprint": approval.fingerprint,
        "summary": approval.summary,
    }


def _raise_sdk_tool_interrupt(sdk: Any, error: ToolApprovalRequired) -> None:
    """Translate an AgentMesh approval signal into the SDK HITL protocol."""

    try:
        interrupt = _sdk_module(
            sdk,
            "openjiuwen.core.single_agent.interrupt",
        )
        response = _sdk_module(
            sdk,
            "openjiuwen.core.single_agent.interrupt.response",
        )
        request = response.InterruptRequest(
            message=error.request.summary,
            payload_schema={"type": "object"},
            metadata={"agentmeshApproval": _approval_metadata(error.request)},
        )
        raise interrupt.ToolInterruptException(request) from error
    except (OpenJiuwenSdkAdapterError, AttributeError, ImportError):
        # A compatibility test double may not expose the optional HITL
        # modules. In that case preserve the original platform signal.
        raise error


def _find_agentmesh_approval(value: Any) -> ToolApprovalRequest | None:
    """Extract an approval envelope from an SDK interrupt result."""

    pending: list[Any] = [value]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        marker = id(current)
        if marker in seen:
            continue
        seen.add(marker)

        if hasattr(current, "model_dump"):
            try:
                current = current.model_dump()
            except Exception:
                pass

        if isinstance(current, dict):
            metadata = current.get("metadata")
            if isinstance(metadata, dict):
                raw = metadata.get("agentmeshApproval")
                if isinstance(raw, dict):
                    try:
                        return ToolApprovalRequest(
                            approval_id=str(raw["approvalId"]),
                            tool_name=str(raw["toolName"]),
                            protocol=str(raw["protocol"]),
                            risk_level=str(raw["riskLevel"]),
                            requires_confirmation=bool(raw["requiresConfirmation"]),
                            arguments=dict(raw.get("arguments") or {}),
                            fingerprint=str(raw["fingerprint"]),
                            summary=str(raw.get("summary") or "需要确认工具调用"),
                        )
                    except (KeyError, TypeError, ValueError):
                        pass
            pending.extend(current.values())
            continue

        if isinstance(current, (list, tuple, set, frozenset)):
            pending.extend(current)
            continue

        for attribute in ("payload", "value", "metadata", "state"):
            nested = getattr(current, attribute, None)
            if nested is not None:
                pending.append(nested)
    return None


@dataclass(slots=True)
class _SdkToolBinding:
    tool: Any
    definition_name: str


def _build_sdk_tools(
    sdk: Any,
    *,
    bridge: Any,
    session_id: str,
    approved_tools: set[str] | frozenset[str] | None,
    deadline_at: float | None,
    cancel_event: asyncio.Event | None,
) -> list[_SdkToolBinding]:
    types = _sdk_types(sdk)
    Tool = types["Tool"]
    ToolCard = types["ToolCard"]
    bindings: list[_SdkToolBinding] = []
    registry = getattr(bridge, "registry", None)
    definitions = registry.list() if registry is not None else []

    def make_tool(definition: Any, index: int) -> _SdkToolBinding:
        name = str(definition.name)

        class RegistryTool(Tool):
            def __init__(self):
                card = ToolCard(
                    id=f"agentmesh-{session_id}-{index}-{name}",
                    name=name,
                    description=definition.description or "",
                    input_params=definition.input_schema or {},
                    properties={
                        "agentmeshProtocol": definition.protocol,
                        "agentmeshRiskLevel": definition.risk_level,
                    },
                    stateless=False,
                    parallel_safe=(definition.risk_level != "high"),
                    idempotent=(definition.side_effect_risk in {"READ_ONLY", "IDEMPOTENT_WRITE"}),
                )
                super().__init__(card)

            async def invoke(self, inputs: dict[str, Any], **kwargs: Any) -> Any:
                if not isinstance(inputs, dict):
                    raise TypeError("tool arguments must be an object")
                try:
                    return await bridge.call(
                        name,
                        dict(inputs),
                        approved_tools=approved_tools,
                        deadline_at=deadline_at,
                        cancel_event=cancel_event,
                    )
                except ToolApprovalRequired as exc:
                    _raise_sdk_tool_interrupt(sdk, exc)

            async def stream(self, inputs: dict[str, Any], **kwargs: Any) -> AsyncIterator[Any]:
                yield await self.invoke(inputs, **kwargs)

        return _SdkToolBinding(RegistryTool(), name)

    for index, definition in enumerate(definitions):
        bindings.append(make_tool(definition, index))
    return bindings


class OpenJiuwenSdkRunner:
    """Run the official OpenJiuwen ReActAgent through AgentMesh boundaries."""

    agent_type = "ReActAgent"

    def __init__(self, sdk: Any, *, max_iterations: int = 8):
        self._sdk = sdk
        self.max_iterations = max(1, int(max_iterations))

    async def run(
        self,
        request: AgentExecutionRequest,
        *,
        model_adapter: OpenJiuwenModelAdapter,
        tool_bridge: Any,
        approved_tools: set[str] | frozenset[str] | None = None,
    ) -> AgentExecutionResult:
        types = _sdk_types(self._sdk)
        runner = getattr(self._sdk, "runner", None)
        if runner is None:
            runner_module = _sdk_module(self._sdk, "openjiuwen.core.runner.runner")
            runner = getattr(runner_module, "Runner", None)
        if runner is None:
            raise OpenJiuwenSdkAdapterError("OpenJiuwen official Runner is unavailable")
        model_adapter._check_control()

        # A Session is execution-local even when the caller supplies an
        # external correlation id.  Reusing that raw id could let two retries
        # or tenants share SDK checkpointer state.  Keep the caller id only in
        # the surrounding AgentMesh trace, never as the SDK key.
        session_id = _new_session_id(request)
        # The adapter is created by the outer executor before the SDK session
        # exists.  Set the generated ID now so model events and gateway audit
        # records carry the same per-execution correlation key.
        model_adapter.session_id = session_id
        set_session_id = getattr(tool_bridge, "set_session_id", None)
        if callable(set_session_id):
            set_session_id(session_id)
        tenant_hash = _tenant_hash(request.tenant_scope or f"agent:{request.agent.id}")
        agent_id = f"agentmesh-{tenant_hash}-{uuid.uuid4().hex}"
        card = types["AgentCard"](
            id=agent_id,
            name=request.agent.name or agent_id,
            description=request.agent.description or "AgentMesh OpenJiuwen agent",
            input_params={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        )
        agent = types["ReActAgent"](card)
        sdk_model = model_adapter.build_sdk_model(self._sdk)
        model_client_config = getattr(sdk_model, "model_client_config", None)
        model_config = getattr(sdk_model, "model_config", None)
        config = types["ReActAgentConfig"](
            model_name=model_adapter.model_name,
            model_provider=getattr(model_client_config, "client_provider", "agentmesh_gateway"),
            model_client_config=model_client_config,
            model_config_obj=model_config,
            max_iterations=self.max_iterations,
            # SDK-side memory/retrieval is disabled for AgentMesh. Use the
            # one-shot session key anyway so a future SDK memory feature cannot
            # accidentally share state between requests in the same tenant.
            mem_scope_id=session_id,
            prompt_template=[
                {
                    "role": "system",
                    "content": (
                        "You are an AgentMesh OpenJiuwen agent. The user task may contain "
                        "scoped Conversation Memory, User Long-term Memory, Retrieved Knowledge, "
                        "and attachment context. Treat those sections as request-local context; "
                        "do not retrieve or write memory directly and do not call tools outside "
                        "the supplied AgentMesh registry."
                    ),
                }
            ],
            parallel_tool_calls=False,
        )
        agent.configure(config)
        agent.set_llm(sdk_model)

        bindings = _build_sdk_tools(
            self._sdk,
            bridge=tool_bridge,
            session_id=session_id,
            approved_tools=approved_tools,
            deadline_at=request.deadline_at,
            cancel_event=request.cancel_event,
        )
        registered_names: list[str] = []
        session = None
        started = time.perf_counter()
        streaming = bool(request.streaming)
        try:
            for binding in bindings:
                model_adapter._check_control()
                add_ability = getattr(agent.ability_manager, "add_ability", None)
                if callable(add_ability):
                    registration = add_ability(binding.tool.card, binding.tool)
                    if getattr(registration, "added", True) is False:
                        raise OpenJiuwenSdkAdapterError(
                            f"failed to register SDK Tool {binding.definition_name}: "
                            f"{getattr(registration, 'reason', 'unknown reason')}"
                        )
                else:
                    result = runner.resource_mgr.add_tool(binding.tool)
                    if getattr(result, "is_err", lambda: False)():
                        raise OpenJiuwenSdkAdapterError(
                            f"failed to register SDK Tool {binding.definition_name}"
                        )
                    agent.ability_manager.add(binding.tool.card)
                registered_names.append(binding.tool.card.name)

            session = types["create_agent_session"](
                session_id=session_id,
                card=card,
                envs={
                    "agentmesh_tenant_scope": tenant_hash,
                    "agentmesh_executor": "openjiuwen",
                },
            )
            model_adapter._check_control()
            inputs = {
                "query": request.task,
                "conversation_id": session_id,
                "user_id": tenant_hash,
                "agentmesh_context_sections": _context_sections(request.task),
            }

            if streaming:
                raw_stream = runner.run_agent_streaming(
                    agent,
                    inputs,
                    session=session,
                )
                chunks: list[str] = []
                final_output = ""
                pending_approval: ToolApprovalRequest | None = None
                async for raw in _controlled_stream(raw_stream, request):
                    payload = _stream_payload(raw)
                    pending_approval = pending_approval or _find_agentmesh_approval(payload)
                    payload_type = str(payload.get("type", "message"))
                    text = _text_from_stream_payload(payload)
                    if payload_type == "llm_output" and text:
                        chunks.append(text)
                    elif payload_type in {"answer", "message"} and text:
                        final_output = text
                    if request.on_runtime_event is not None:
                        request.on_runtime_event(
                            {
                                "kind": "openjiuwen_stream",
                                "status": "running",
                                "executor": "openjiuwen",
                                "sessionId": session_id,
                                "payload": payload,
                            }
                        )
                content = "".join(chunks) or final_output
                result_value: Any = {"output": content, "result_type": "answer"}
                if pending_approval is not None:
                    raise ToolApprovalRequired(pending_approval)
            else:
                result_value = await _await_with_controls(
                    runner.run_agent(agent, inputs, session=session),
                    request,
                )
                content = _result_text(result_value)

            approval = _find_agentmesh_approval(result_value)
            if approval is not None:
                raise ToolApprovalRequired(approval)

            return AgentExecutionResult(
                content=content,
                metadata={
                    "protocol": request.agent.protocol,
                    "executor": "openjiuwen",
                    "executorType": "openjiuwen",
                    "agentId": request.agent.id,
                    "agentType": type(agent).__name__,
                    "sdk": True,
                    "sdkVersion": _sdk_version(self._sdk),
                    "sessionId": session_id,
                    "iterations": max(1, model_adapter.model_calls),
                    "modelCalls": model_adapter.model_calls,
                    "streamCalls": model_adapter.stream_calls,
                    "streaming": streaming,
                    "toolCount": len(bindings),
                    "registeredTools": registered_names,
                    "attachmentCount": len(request.attachments),
                    "contextSections": _context_sections(request.task),
                    "elapsedMs": int((time.perf_counter() - started) * 1000),
                },
            )
        finally:
            # Runner.release clears the SDK checkpointer/session state. The
            # AbilityManager teardown removes stateful temporary tools from the
            # process-global resource manager even on cancellation or timeout.
            if session is not None:
                try:
                    # Runner calls this on the normal path.  Calling the
                    # official Session hook again is idempotent and closes the
                    # stream/checkpointer when cancellation interrupts the
                    # generator before Runner reaches its post-run hook.
                    post_run = getattr(session, "post_run", None)
                    if callable(post_run):
                        post_run_result = post_run()
                        if inspect.isawaitable(post_run_result):
                            await post_run_result
                except asyncio.CancelledError:
                    pass
                except Exception:
                    logger.warning(
                        "OpenJiuwen Session.post_run failed for session %s",
                        session_id,
                        exc_info=True,
                    )
                try:
                    release_result = runner.release(session_id, force=True)
                    if inspect.isawaitable(release_result):
                        await release_result
                except asyncio.CancelledError:
                    pass
                except Exception:
                    logger.warning(
                        "OpenJiuwen temporary tool teardown failed for session %s",
                        session_id,
                        exc_info=True,
                    )
            teardown = getattr(agent.ability_manager, "teardown_tools", None)
            if callable(teardown):
                try:
                    teardown_result = teardown()
                    if inspect.isawaitable(teardown_result):
                        await teardown_result
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass


async def _controlled_stream(source: Any, request: AgentExecutionRequest) -> AsyncIterator[Any]:
    """Forward an SDK stream while allowing deadline/cancel to interrupt it."""

    queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

    async def producer() -> None:
        try:
            stream = await source if inspect.isawaitable(source) else source
            async for item in stream:
                await queue.put(("item", item))
            await queue.put(("done", None))
        except BaseException as exc:
            await queue.put(("error", exc))

    task = asyncio.create_task(producer())
    try:
        while True:
            remaining = _remaining_deadline(request)
            get_task = asyncio.create_task(queue.get())
            cancel_task = (
                asyncio.create_task(request.cancel_event.wait())
                if request.cancel_event is not None
                else None
            )
            wait_set: set[asyncio.Task[Any]] = {get_task}
            if cancel_task is not None:
                wait_set.add(cancel_task)
            try:
                done, _ = await asyncio.wait(wait_set, timeout=remaining)
                if cancel_task is not None and cancel_task in done and request.cancel_event.is_set():
                    get_task.cancel()
                    await asyncio.gather(get_task, return_exceptions=True)
                    raise asyncio.CancelledError
                if get_task not in done:
                    get_task.cancel()
                    await asyncio.gather(get_task, return_exceptions=True)
                    raise OpenJiuwenSdkDeadlineError("OPENJIUWEN_DEADLINE_EXCEEDED")
                kind, value = get_task.result()
            finally:
                if cancel_task is not None and not cancel_task.done():
                    cancel_task.cancel()
                    await asyncio.gather(cancel_task, return_exceptions=True)
            if kind == "item":
                yield value
            elif kind == "done":
                return
            else:
                raise value
    finally:
        if not task.done():
            task.cancel()
        try:
            await asyncio.gather(task, return_exceptions=True)
        except asyncio.CancelledError:
            pass
        except Exception:
            # Preserve the caller's cancellation while making a best-effort
            # attempt to stop the SDK producer task.
            pass


__all__ = [
    "OpenJiuwenModelAdapter",
    "OpenJiuwenSdkAdapterError",
    "OpenJiuwenSdkDeadlineError",
    "OpenJiuwenSdkRunner",
]
