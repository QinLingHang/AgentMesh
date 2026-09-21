"""OpenJiuwen Agent executor (P37 §7.1, adapter execution plan V1.0).

OpenJiuwen-developed Agents are selected by ``agent.executor_type``:

    protocol=internal  executorType=native     -> existing InternalAgentPlugin
    protocol=internal  executorType=openjiuwen -> OpenJiuwenAgentExecutor
    protocol!=internal executorType=openjiuwen -> configuration error

The executor is a standalone AgentExecutor implementation. It deliberately
does NOT reuse the InternalAgentPlugin prompt or ToolLoopRunner: OpenJiuwen
runs its own bounded framework-style loop over the AgentMesh model runtime
and calls AgentMesh tools exclusively through the request-scoped
ToolRegistry (so governance, approval, schema validation, timeouts, the
P37 Guard and event conversion stay in one place).

Tool / MCP / RAG boundaries:

    - Tool & MCP descriptors are projected from the ToolRegistry; callbacks
      always go back through ToolRegistry.execute(). OpenJiuwen never
      connects to MCP servers or tools directly.
    - RAG / memory are consumed from the prepared ``request.task``
      context; OpenJiuwen-side retrieval/memory stay disabled so knowledge
      scope and citations cannot be bypassed.
    - Model calls run through the AgentMesh model gateway (events, token
      usage, timeouts). OpenJiuwen never reads model credentials itself.

Dependency policy: with ``openjiuwen_execution_mode=sdk`` the OpenJiuwen
package must be importable; a missing/unusable SDK fails explicitly and
never silently degrades to another executor.
"""

import asyncio

from time import (
    monotonic as time_monotonic,
    perf_counter,
)

from typing import (
    Any,
    Protocol,
    runtime_checkable,
)

from app.agents.contracts import (
    AgentExecutionRequest,
    AgentExecutionResult,
)
from app.agents.openjiuwen_runtime import (
    OpenJiuwenRuntimeError,
    get_active_openjiuwen_sdk,
    validate_execution_mode,
)
from app.agents.openjiuwen_sdk import (
    OpenJiuwenModelAdapter,
    OpenJiuwenSdkAdapterError,
    OpenJiuwenSdkDeadlineError,
    OpenJiuwenSdkRunner,
    _find_agentmesh_approval,
)
from app.config import (
    settings,
)
from app.models.contracts import ModelMessage, ModelTool
from app.tools import (
    ToolApprovalRequest,
    ToolApprovalRequired,
    ToolDefinition,
    ToolError,
    ToolErrorType,
    ToolRegistry,
)


class OpenJiuwenUnavailableError(
    RuntimeError,
):
    """OpenJiuwen SDK/configuration is unavailable for this execution."""


class OpenJiuwenExecutionError(
    RuntimeError,
):
    """The OpenJiuwen agent execution failed inside the framework loop."""


def _find_exception_in_chain(
    error: BaseException,
    expected: type[BaseException],
) -> BaseException | None:
    """Find a platform control-flow exception hidden by an SDK wrapper."""

    pending: list[BaseException] = [error]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        marker = id(current)
        if marker in seen:
            continue
        seen.add(marker)
        if isinstance(current, expected):
            return current
        for attribute in ("__cause__", "__context__", "cause"):
            nested = getattr(current, attribute, None)
            if isinstance(nested, BaseException):
                pending.append(nested)
    return None


# =========================================================
# Tool bridge
# =========================================================


class OpenJiuwenToolBridge:
    """Projects ToolRegistry tools as OpenJiuwen tool descriptors and routes
    every callback back through ToolRegistry.

    Sequence per call (identical to the platform boundary):

        authorize (governance / approval) -> ToolRegistry.execute()
        (schema validation, adapter, timeout, error normalization)
    """

    def __init__(
        self,
        registry: ToolRegistry | None,
        *,
        on_tool_event: Any = None,
    ):
        self._registry = registry

        self._on_tool_event = on_tool_event
        self._session_id = ""

    @property
    def registry(self) -> ToolRegistry | None:
        """Expose the request-scoped registry to the SDK projection only."""

        return self._registry

    def set_session_id(self, session_id: str) -> None:
        """Attach the request-local SDK session to subsequent audit events."""

        self._session_id = str(session_id or "")

    @property
    def available(
        self,
    ) -> bool:
        return (
            self._registry is not None
            and bool(
                self._registry.list(),
            )
        )

    def descriptors(
        self,
    ) -> list[ModelTool]:
        if not self.available:
            return []

        return [
            ModelTool(
                name=tool.name,
                description=tool.description,
                input_schema=tool.input_schema,
            )
            for tool in self._registry.list()
        ]

    def _emit(
        self,
        title: str,
        status: str,
        tool: ToolDefinition | None = None,
        **detail: Any,
    ) -> None:
        if self._on_tool_event is None:
            return

        payload = {
            "title": title,
            "status": status,
            "tool": (
                tool.name
                if tool is not None
                else ""
            ),
            "protocol": (
                tool.protocol
                if tool is not None
                else ""
            ),
            "risk_level": (
                tool.risk_level
                if tool is not None
                else ""
            ),
            "requires_confirmation": (
                tool.requires_confirmation
                if tool is not None
                else False
            ),
        }

        payload.update(
            detail,
        )
        payload.setdefault("executorType", "openjiuwen")
        if self._session_id:
            payload.setdefault("sessionId", self._session_id)

        self._on_tool_event(
            payload,
        )

    async def call(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        approved_tools: set[str]
        | frozenset[str]
        | None = None,
        deadline_at: float | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> Any:
        if self._registry is None:
            raise ToolError(
                ToolErrorType.UNAVAILABLE,
                "OpenJiuwen tool registry is unavailable",
            )
        if cancel_event is not None and cancel_event.is_set():
            raise asyncio.CancelledError
        if deadline_at is not None and time_monotonic() >= deadline_at:
            raise TimeoutError("OPENJIUWEN_DEADLINE_EXCEEDED")

        tool = self._registry.get(
            name,
        )

        # -------------------------------------------------
        # Governance preflight: approval is a normal suspend
        # state and must surface as ToolApprovalRequired,
        # never as a plain agent failure.
        # -------------------------------------------------

        try:
            self._registry.authorize(
                name,
                approved_tools=approved_tools,
            )

        except ToolError as exc:
            if (
                exc.error_type
                is ToolErrorType.REQUIRES_APPROVAL
            ):
                self._emit(
                    "Tool Approval Required",
                    "completed",
                    tool=tool,
                )

                raise ToolApprovalRequired(
                    ToolApprovalRequest.create(
                        tool,
                        arguments,
                    ),
                ) from exc

            raise

        self._emit(
            "Tool Started",
            "running",
            tool=tool,
        )

        started = perf_counter()

        try:
            execute = self._registry.execute(
                name,
                arguments,
                approved_tools=approved_tools,
            )
            remaining = None
            if deadline_at is not None:
                remaining = deadline_at - time_monotonic()
                if remaining <= 0:
                    raise TimeoutError("OPENJIUWEN_DEADLINE_EXCEEDED")
            if cancel_event is None and remaining is None:
                result = await execute
            else:
                execute_task = asyncio.create_task(execute)
                cancel_task = (
                    asyncio.create_task(cancel_event.wait())
                    if cancel_event is not None
                    else None
                )
                wait_set = {execute_task}
                if cancel_task is not None:
                    wait_set.add(cancel_task)
                try:
                    done, _ = await asyncio.wait(wait_set, timeout=remaining)
                    # A completed tool call is already a committed side
                    # effect; only interrupt a still-running call so the SDK
                    # cannot mistake a committed action for a retryable
                    # timeout/cancellation.
                    if (
                        execute_task not in done
                        and cancel_task is not None
                        and cancel_task in done
                        and cancel_event.is_set()
                    ):
                        execute_task.cancel()
                        await asyncio.gather(execute_task, return_exceptions=True)
                        raise asyncio.CancelledError
                    if execute_task not in done:
                        execute_task.cancel()
                        await asyncio.gather(execute_task, return_exceptions=True)
                        raise TimeoutError("OPENJIUWEN_DEADLINE_EXCEEDED")
                    result = await execute_task
                finally:
                    if cancel_task is not None and not cancel_task.done():
                        cancel_task.cancel()
                        await asyncio.gather(cancel_task, return_exceptions=True)

        except ToolError as exc:
            self._emit(
                "Tool Failed",
                "error",
                tool=tool,
                latency_ms=int(
                    (
                        perf_counter()
                        - started
                    )
                    * 1000,
                ),
                error={
                    "type": exc.error_type.value,
                    "message": str(exc),
                },
            )

            raise

        except asyncio.CancelledError:
            self._emit(
                "Tool Cancelled",
                "canceled",
                tool=tool,
                latency_ms=int((perf_counter() - started) * 1000),
            )
            raise

        except TimeoutError as exc:
            self._emit(
                "Tool Failed",
                "error",
                tool=tool,
                latency_ms=int((perf_counter() - started) * 1000),
                error={"type": ToolErrorType.TIMEOUT.value, "message": str(exc)},
            )
            if str(exc) == "OPENJIUWEN_DEADLINE_EXCEEDED":
                raise OpenJiuwenSdkDeadlineError(str(exc)) from exc
            raise ToolError(ToolErrorType.TIMEOUT, str(exc)) from exc

        self._emit(
            "Tool Completed",
            "completed",
            tool=tool,
            latency_ms=int(
                (
                    perf_counter()
                    - started
                )
                * 1000,
            ),
        )

        return result


# =========================================================
# Runner
# =========================================================


@runtime_checkable
class OpenJiuwenAgentRunner(
    Protocol,
):
    async def run(
        self,
        request: AgentExecutionRequest,
        *,
        model_adapter: OpenJiuwenModelAdapter,
        tool_bridge: OpenJiuwenToolBridge,
        approved_tools: set[str]
        | frozenset[str]
        | None = None,
    ) -> AgentExecutionResult: ...


class BuiltinOpenJiuwenRunner:
    """Deterministic in-process OpenJiuwen framework loop.

    Bounded iterations; no hidden retries (retries belong to the harness
    unified budget); every tool callback goes through the tool bridge.
    """

    def __init__(
        self,
        *,
        max_iterations: int = 8,
    ):
        self.max_iterations = max(
            1,
            max_iterations,
        )

    async def run(
        self,
        request: AgentExecutionRequest,
        *,
        model_adapter: OpenJiuwenModelAdapter,
        tool_bridge: OpenJiuwenToolBridge,
        approved_tools: set[str]
        | frozenset[str]
        | None = None,
    ) -> AgentExecutionResult:
        session_messages: list[ModelMessage] = [
            ModelMessage(
                role="system",
                content=(
                    "You are an OpenJiuwen agent executed inside the "
                    "AgentMesh runtime. Complete the assigned subtask; "
                    "use the provided tools when needed."
                ),
            ),
            ModelMessage(
                role="user",
                content=request.task,
            ),
        ]

        tools = tool_bridge.descriptors()

        for iteration in range(
            1,
            self.max_iterations + 1,
        ):
            response = await model_adapter.generate(
                session_messages,
                tools,
            )

            if not response.tool_calls:
                return AgentExecutionResult(
                    content=response.content,
                    metadata=_runner_metadata(
                        request,
                        iterations=iteration,
                    ),
                )

            session_messages.append(
                ModelMessage(
                    role="assistant",
                    content=response.content,
                    tool_calls=response.tool_calls,
                ),
            )

            for call in response.tool_calls:
                result = await tool_bridge.call(
                    call.name,
                    call.arguments,
                    approved_tools=approved_tools,
                    deadline_at=request.deadline_at,
                    cancel_event=request.cancel_event,
                )

                session_messages.append(
                    ModelMessage(
                        role="tool",
                        tool_call_id=call.id,
                        content=_stringify_tool_result(
                            result,
                        ),
                    ),
                )

        raise OpenJiuwenExecutionError(
            (
                "OPENJIUWEN_MAX_ITERATIONS "
                f"({self.max_iterations}) exceeded"
            ),
        )


# Backwards-compatible import name for callers that imported the old class.
# The implementation is now the official Runner/ReActAgent adapter in the
# narrow ``openjiuwen_sdk`` module; it no longer probes a fictional
# ``AgentRunner`` symbol.
SdkOpenJiuwenRunner = OpenJiuwenSdkRunner


def _runner_metadata(
    request: AgentExecutionRequest,
    *,
    iterations: int,
    sdk: bool = False,
    **detail: Any,
) -> dict[str, Any]:
    metadata = {
        "protocol": request.agent.protocol,
        "executor": "openjiuwen",
        "executorType": "openjiuwen",
        "agentId": request.agent.id,
        "iterations": iterations,
        "sdk": sdk,
    }
    metadata.update(detail)
    return metadata


def _stringify_tool_result(
    result: Any,
) -> str:
    import json

    if isinstance(
        result,
        str,
    ):
        return result

    try:
        return json.dumps(
            result,
            ensure_ascii=False,
            default=str,
        )

    except (
        TypeError,
        ValueError,
    ):
        return str(
            result,
        )


# =========================================================
# Executor
# =========================================================


class OpenJiuwenAgentExecutor:
    """Standalone AgentExecutor for agents with executorType=openjiuwen."""

    def __init__(
        self,
        *,
        execution_mode: str | None = None,
        max_iterations: int | None = None,
    ):
        self._execution_mode = (
            execution_mode
            if execution_mode is not None
            else settings.openjiuwen_execution_mode
        )

        self._max_iterations = (
            max_iterations
            if max_iterations is not None
            else settings.openjiuwen_max_tool_iterations
        )

    # -------------------------------------------------
    # Runner resolution (explicit failure, no fallback)
    # -------------------------------------------------

    def resolve_runner(
        self,
    ) -> OpenJiuwenAgentRunner:
        try:
            mode = validate_execution_mode(
                self._execution_mode,
                allow_builtin=settings.openjiuwen_allow_builtin,
            )
        except OpenJiuwenRuntimeError as exc:
            raise OpenJiuwenUnavailableError(str(exc)) from exc

        if mode == "sdk":
            sdk = get_active_openjiuwen_sdk()
            if sdk is None:
                raise OpenJiuwenUnavailableError(
                    "OpenJiuwen Runner is not initialized; the FastAPI "
                    "lifespan must start the pinned SDK before requests "
                    "can execute (openjiuwen=="
                    f"{settings.openjiuwen_sdk_version})"
                )

            return OpenJiuwenSdkRunner(
                sdk,
                max_iterations=self._max_iterations,
            )

        if mode == "builtin":
            return BuiltinOpenJiuwenRunner(
                max_iterations=self._max_iterations,
            )

        raise OpenJiuwenUnavailableError(
            (
                f"unknown OPENJIUWEN_EXECUTION_MODE: {mode}; "
                "expected 'builtin' or 'sdk'"
            ),
        )

    # -------------------------------------------------
    # AgentExecutor contract
    # -------------------------------------------------

    async def execute(
        self,
        request: AgentExecutionRequest,
    ) -> AgentExecutionResult:
        self._emit_runtime(
            request,
            "OpenJiuwen Agent Started",
            "running",
        )

        model_runtime = request.model_runtime

        if model_runtime is None:
            raise OpenJiuwenUnavailableError(
                (
                    "OpenJiuwen agent execution requires a resolved "
                    "AgentMesh model runtime; model configuration is "
                    "missing for this request"
                ),
            )

        started = perf_counter()

        runner = self.resolve_runner()

        tool_bridge = OpenJiuwenToolBridge(
            request.tool_registry,
            on_tool_event=request.on_tool_event,
        )

        try:
            result = await runner.run(
                request,
                model_adapter=OpenJiuwenModelAdapter(
                    model_runtime,
                    attachments=request.attachments,
                    on_model_event=request.on_model_event,
                    deadline_at=request.deadline_at,
                    cancel_event=request.cancel_event,
                    session_id=request.session_id or "",
                ),
                tool_bridge=tool_bridge,
                approved_tools=request.approved_tools,
            )

        except OpenJiuwenSdkDeadlineError as exc:
            self._emit_runtime(
                request,
                "OpenJiuwen Agent Deadline Exceeded",
                "error",
                errorType="deadline_exceeded",
                message=str(exc),
            )
            raise OpenJiuwenExecutionError(str(exc)) from exc

        except OpenJiuwenSdkAdapterError as exc:
            self._emit_runtime(
                request,
                "OpenJiuwen SDK Adapter Failed",
                "error",
                errorType="sdk_incompatible",
                message=str(exc)[:300],
            )
            raise OpenJiuwenUnavailableError(str(exc)) from exc

        except asyncio.CancelledError:
            self._emit_runtime(
                request,
                "OpenJiuwen Agent Canceled",
                "canceled",
            )
            raise

        except Exception as exc:
            approval = _find_exception_in_chain(exc, ToolApprovalRequired)
            if approval is None:
                # Some SDK versions surface the HITL envelope on the
                # interrupt exception instead of retaining the original
                # ToolApprovalRequired as its cause.
                approval = _find_agentmesh_approval(exc)
            if approval is not None:
                # The SDK AbilityManager may wrap tool exceptions while
                # building its ToolMessage. Preserve the platform approval
                # control-flow signal instead of converting it to a retryable
                # agent failure.
                raise approval from exc
            deadline = _find_exception_in_chain(
                exc,
                OpenJiuwenSdkDeadlineError,
            )
            if deadline is not None:
                self._emit_runtime(
                    request,
                    "OpenJiuwen Agent Deadline Exceeded",
                    "error",
                    errorType="deadline_exceeded",
                    message=str(deadline),
                )
                raise OpenJiuwenExecutionError(str(deadline)) from exc
            self._emit_runtime(
                request,
                "OpenJiuwen Agent Failed",
                "error",
                errorType=type(exc).__name__,
                message=str(exc)[:300],
            )

            raise

        self._emit_runtime(
            request,
            "OpenJiuwen Agent Completed",
            "completed",
            elapsedMs=int(
                (
                    perf_counter()
                    - started
                )
                * 1000,
            ),
            iterations=result.metadata.get(
                "iterations",
            ),
            metadata=dict(result.metadata),
        )

        return result

    def _emit_runtime(
        self,
        request: AgentExecutionRequest,
        title: str,
        status: str,
        **detail: Any,
    ) -> None:
        if request.on_runtime_event is None:
            return

        request.on_runtime_event(
            {
                "kind": "openjiuwen",
                "title": title,
                "status": status,
                "agent": request.agent.name,
                "capability": request.capability,
                "executor": "openjiuwen",
                **detail,
            },
        )
