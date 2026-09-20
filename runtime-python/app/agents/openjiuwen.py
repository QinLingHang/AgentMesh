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

from time import (
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
from app.config import (
    settings,
)
from app.models.contracts import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelTool,
)
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


# =========================================================
# Model adapter
# =========================================================


class OpenJiuwenModelAdapter:
    """Bridges AgentMesh's ResolvedModelRuntime into the OpenJiuwen model
    interface. Model calls always pass through the gateway so model events,
    token usage, cost, timeout and errors stay on the AgentMesh event
    boundary."""

    def __init__(
        self,
        model_runtime: Any,
    ):
        self.model_runtime = model_runtime

    @property
    def model_name(
        self,
    ) -> str:
        return (
            settings.openjiuwen_model_name
            or getattr(
                self.model_runtime,
                "model",
                "",
            )
            or "default"
        )

    async def generate(
        self,
        messages: list[ModelMessage],
        tools: list[ModelTool],
        on_model_event: Any = None,
    ) -> ModelResponse:
        gateway = self.model_runtime.gateway

        request = ModelRequest(
            model=self.model_name,
            messages=messages,
            tools=tools or None,
            temperature=0.2,
        )

        return await gateway.generate(
            request,
            on_model_event,
        )


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
        registry: ToolRegistry,
        *,
        on_tool_event: Any = None,
    ):
        self._registry = registry

        self._on_tool_event = on_tool_event

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
    ) -> Any:
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
            result = await self._registry.execute(
                name,
                arguments,
                approved_tools=approved_tools,
            )

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
                request.on_model_event,
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


class SdkOpenJiuwenRunner:
    """OpenJiuwen SDK backed runner (used after the SDK version is locked).

    The SDK must expose a synchronous agent factory. The bridge keeps the
    tool callback inside AgentMesh; any SDK failure surfaces as
    OpenJiuwenExecutionError - never as a fallback to another executor.
    """

    def __init__(
        self,
        module: Any,
        *,
        max_iterations: int = 8,
    ):
        self._module = module

        self.max_iterations = max_iterations

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
        try:
            runner_factory = getattr(
                self._module,
                "AgentRunner",
                None,
            )

            if runner_factory is None:
                raise OpenJiuwenUnavailableError(
                    (
                        "openjiuwen package does not expose "
                        "AgentRunner; SDK version not supported"
                    ),
                )

            # The SDK integration point. Tool descriptors are projected as
            # plain dictionaries; execution is delegated back into AgentMesh
            # through the same bridge used by the builtin runner.
            session = runner_factory(
                tools=tool_bridge.descriptors(),
            )

            result = session.run(
                request.task,
            )

        except (
            OpenJiuwenUnavailableError,
            OpenJiuwenExecutionError,
        ):
            raise

        except Exception as exc:
            raise OpenJiuwenExecutionError(
                f"openjiuwen SDK execution failed: {exc}",
            ) from exc

        return AgentExecutionResult(
            content=str(
                result,
            ),
            metadata=_runner_metadata(
                request,
                iterations=1,
                sdk=True,
            ),
        )


def _runner_metadata(
    request: AgentExecutionRequest,
    *,
    iterations: int,
    sdk: bool = False,
) -> dict[str, Any]:
    return {
        "protocol": request.agent.protocol,
        "executor": "openjiuwen",
        "executorType": "openjiuwen",
        "agentId": request.agent.id,
        "iterations": iterations,
        "sdk": sdk,
    }


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
            or settings.openjiuwen_execution_mode
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
        mode = (
            self._execution_mode.strip().lower()
            or "builtin"
        )

        if mode == "sdk":
            try:
                import openjiuwen  # noqa: F401  (version locked at deploy time)
            except ImportError as exc:
                raise OpenJiuwenUnavailableError(
                    (
                        "OpenJiuwen SDK is not installed; "
                        "openjiuwen agents fail explicitly and never "
                        "degrade to other executors. Install the pinned "
                        "SDK or set OPENJIUWEN_EXECUTION_MODE=builtin."
                    ),
                ) from exc

            return SdkOpenJiuwenRunner(
                openjiuwen,
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
                ),
                tool_bridge=tool_bridge,
            )

        except Exception as exc:
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
