import asyncio
import json
import time

from collections.abc import (
    Callable,
)

from typing import Any

from app.models import (
    ModelInputAttachment,
    ModelMessage,
    ModelRequest,
    ModelTool,
)

from app.tools.contracts import (
    ToolError,
    ToolErrorType,
)
from app.tools.approval import (
    ToolApprovalRequest,
    ToolApprovalRequired,
)

from app.tools.registry import (
    ToolRegistry,
)


SENSITIVE = (
    "authorization",
    "api_key",
    "apikey",
    "password",
    "token",
    "secret",
    "credential",
    "otp",
)


def safe(
    value: Any,
) -> Any:
    if isinstance(value, str):
        lower = value.lower()
        if any(
            marker in lower
            for marker in (
                "password=",
                "password:",
                "token=",
                "token:",
                "credential=",
                "credential:",
                "otp=",
                "otp:",
                "authorization:",
                "bearer ",
            )
        ):
            return "[REDACTED]"
        if len(value) > 2000:
            return value[:2000] + "…[TRUNCATED]"
        return value

    if isinstance(
        value,
        dict,
    ):
        return {
            key: (
                "[REDACTED]"
                if any(
                    item
                    in key.lower()
                    for item
                    in SENSITIVE
                )
                else safe(
                    item_value
                )
            )
            for (
                key,
                item_value,
            )
            in value.items()
        }

    if isinstance(
        value,
        list,
    ):
        return [
            safe(item)
            for item
            in value
        ]

    return value


class ToolLoopRunner:
    def __init__(
        self,
        gateway,
        model: str,
        registry: ToolRegistry,
        max_iterations: int = 5,
        approved_tools: (
            set[str]
            | None
        ) = None,
        max_retries: int = 1,
        retry_backoff_seconds: float = 0.1,
    ):
        self.gateway = gateway

        self.model = model

        self.registry = (
            registry
        )

        self.max_iterations = (
            max(
                1,
                max_iterations,
            )
        )

        # =================================================
        # Approval Grant
        #
        # 当前 MVP 只做到 Runtime 内部显式授权。
        #
        # 默认：
        #     empty set
        #
        # 未来：
        #
        # React Approve
        #       ↓
        # Go Approval Record
        #       ↓
        # Resume Runtime
        #       ↓
        # approved_tools
        # =================================================

        self.approved_tools = (
            set(
                approved_tools
                or set()
            )
        )

        self.max_retries = max(
            0,
            int(max_retries),
        )

        self.retry_backoff_seconds = max(
            0.0,
            float(retry_backoff_seconds),
        )

    async def run(
        self,
        prompt: str,
        on_model_event=None,
        on_tool_event: (
            Callable[
                [dict[str, Any]],
                None,
            ]
            | None
        ) = None,
        attachments: list[ModelInputAttachment] | None = None,
    ) -> str:

        messages = [
            ModelMessage(
                role="system",

                content=(
                    "You are an AgentMesh "
                    "Runtime execution model."
                ),
            ),

            ModelMessage(
                role="user",
                content=prompt,
            ),
        ]

        # =================================================
        # Important:
        #
        # high-risk Tool 仍然暴露给模型。
        #
        # 因为模型必须能够：
        #
        # “我想调用这个 Tool”
        #
        # Runtime 才能产生：
        #
        # “需要人工批准”
        #
        # 如果直接从 tools schema 中隐藏，
        # 就没有 HITL request 这个过程了。
        #
        # disabled Tool 则不暴露。
        # =================================================

        tools = [
            ModelTool(
                name=tool.name,

                description=(
                    tool.description
                ),

                input_schema=(
                    tool.input_schema
                ),
            )

            for tool
            in self.registry.list()

            if tool.enabled
        ]

        for iteration in range(
            self.max_iterations
        ):
            response = (
                await self.gateway
                .generate(
                    ModelRequest(
                        model=(
                            self.model
                        ),

                        messages=(
                            messages
                        ),

                        tools=(
                            tools
                        ),

                        temperature=0.2,
                        attachments=(
                            list(attachments or [])
                            if iteration == 0
                            else []
                        ),
                    ),

                    on_model_event,
                )
            )

            if not (
                response.tool_calls
            ):
                return (
                    response.content
                )

            messages.append(
                ModelMessage(
                    role="assistant",

                    content=(
                        response.content
                    ),

                    tool_calls=(
                        response
                        .tool_calls
                    ),
                )
            )

            for call in (
                response.tool_calls
            ):
                tool = (
                    self.registry
                    .get(
                        call.name
                    )
                )

                def emit(
                    title: str,
                    status: str,
                    **detail,
                ) -> None:
                    if (
                        on_tool_event
                        is not None
                    ):
                        on_tool_event(
                            {
                                "title":
                                    title,

                                "status":
                                    status,

                                "tool":
                                    call.name,

                                "protocol":
                                    tool.protocol,

                                "risk_level":
                                    tool
                                    .risk_level,

                                "requires_confirmation":
                                    tool
                                    .requires_confirmation,

                                **detail,
                            }
                        )

                # =========================================
                # Tool Selected
                # =========================================

                emit(
                    "Tool Selected",
                    "completed",

                    arguments=(
                        safe(
                            call.arguments
                        )
                    ),
                )

                # =========================================
                # Governance Preflight
                #
                # 注意：
                #
                # 先做 Governance，
                # 再发 Tool Started。
                #
                # 这样被阻断的 Tool
                # 不会被 Observability
                # 错误计算为真实 Tool Call。
                # =========================================

                try:
                    self.registry.authorize(
                        call.name,

                        approved_tools=(
                            self
                            .approved_tools
                        ),
                    )

                except ToolError as exc:

                    # -------------------------------------
                    # HITL Foundation
                    #
                    # 需要审批不是：
                    #
                    # Agent Failure
                    # Tool Runtime Failure
                    #
                    # 它是一个正常的安全决策。
                    #
                    # 因此：
                    #
                    # 不 re-raise
                    # 不触发 Rescheduler
                    # 不执行 Tool
                    # -------------------------------------

                    if (
                        exc.error_type
                        == (
                            ToolErrorType
                            .REQUIRES_APPROVAL
                        )
                    ):
                        approval = (
                            ToolApprovalRequest
                            .create(
                                tool,
                                call.arguments,
                            )
                        )

                        emit(
                            (
                                "Tool Approval "
                                "Required"
                            ),
                            "completed",

                            approval_id=(
                                approval
                                .approval_id
                            ),

                            fingerprint=(
                                approval
                                .fingerprint
                            ),

                            reason=(
                                str(exc)
                            ),

                            arguments=(
                                approval
                                .safe_arguments()
                            ),
                        )

                        # HITL is control flow, not a model answer.
                        # Bubble the exact immutable action to Runtime so Go
                        # can persist it and wait for an explicit user decision.
                        raise ToolApprovalRequired(
                            approval
                        ) from exc

                    # -------------------------------------
                    # Permission Denied
                    #
                    # disabled 等是真正的阻断。
                    # -------------------------------------

                    emit(
                        "Tool Blocked",
                        "error",

                        error={
                            "type":
                                exc
                                .error_type
                                .value,

                            "message":
                                str(exc),
                        },
                    )

                    raise

                # =========================================
                # Tool Started
                # =========================================

                emit(
                    "Tool Started",
                    "running",
                )

                started = (
                    time.perf_counter()
                )

                result = None
                last_error: ToolError | None = None

                for attempt in range(
                    self.max_retries + 1
                ):
                    try:
                        result = (
                            await self.registry
                            .execute(
                                call.name,

                                call.arguments,

                                approved_tools=(
                                    self
                                    .approved_tools
                                ),
                            )
                        )
                        last_error = None
                        break

                    except ToolError as exc:
                        last_error = exc
                        retryable = (
                            exc.error_type
                            in {
                                ToolErrorType.TIMEOUT,
                                ToolErrorType.UNAVAILABLE,
                            }
                        )
                        can_retry = (
                            retryable
                            and attempt < self.max_retries
                        )

                        if can_retry:
                            emit(
                                "Tool Retry",
                                "running",
                                attempt=attempt + 1,
                                max_retries=self.max_retries,
                                error={
                                    "type": exc.error_type.value,
                                    "message": str(exc),
                                },
                            )
                            if self.retry_backoff_seconds > 0:
                                await asyncio.sleep(
                                    self.retry_backoff_seconds
                                    * (2 ** attempt)
                                )
                            continue

                        break

                if last_error is not None:
                    exc = last_error
                    title = (
                        "Tool Blocked"

                        if (
                            exc.error_type
                            in {
                                ToolErrorType.REQUIRES_APPROVAL,
                                ToolErrorType.PERMISSION_DENIED,
                            }
                        )

                        else "Tool Failed"
                    )

                    emit(
                        title,
                        "error",

                        latency_ms=int(
                            (
                                time.perf_counter()
                                - started
                            )
                            * 1000
                        ),

                        error={
                            "type": exc.error_type.value,
                            "message": str(exc),
                        },
                    )

                    raise exc

                emit(
                    "Tool Completed",
                    "completed",

                    latency_ms=int(
                        (
                            time.perf_counter()
                            - started
                        )
                        * 1000
                    ),

                    result=(
                        safe(result)
                    ),
                )

                messages.append(
                    ModelMessage(
                        role="tool",

                        tool_call_id=(
                            call.id
                        ),

                        content=(
                            json.dumps(
                                result,
                                ensure_ascii=False,
                            )
                        ),
                    )
                )

        raise ToolError(
            ToolErrorType
            .EXECUTION_FAILED,

            (
                "MAX_TOOL_ITERATIONS "
                f"({self.max_iterations}) "
                "exceeded"
            ),
        )