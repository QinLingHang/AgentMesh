import asyncio

from collections.abc import (
    Awaitable,
    Callable,
)

from typing import Any

import httpx

from app.tools.contracts import (
    ToolDefinition,
    ToolError,
    ToolErrorType,
)

from app.tools.governance import (
    ToolGovernancePolicy,
)


InternalHandler = Callable[
    [dict[str, Any]],
    Awaitable[Any] | Any,
]


class InternalToolAdapter:
    def __init__(
        self,
        handler: InternalHandler,
    ):
        self.handler = (
            handler
        )

    async def execute(
        self,
        tool: ToolDefinition,
        arguments: dict[
            str,
            Any,
        ],
        timeout: float,
    ) -> Any:
        result = (
            self.handler(
                arguments
            )
        )

        if hasattr(
            result,
            "__await__",
        ):
            result = (
                await asyncio.wait_for(
                    result,
                    timeout,
                )
            )

        return result


class HTTPToolAdapter:
    async def execute(
        self,
        tool: ToolDefinition,
        arguments: dict[
            str,
            Any,
        ],
        timeout: float,
    ) -> Any:

        if not tool.endpoint:
            raise ToolError(
                ToolErrorType
                .INVALID_ARGUMENTS,

                (
                    "HTTP tool endpoint "
                    "is required"
                ),
            )

        try:
            async with (
                httpx.AsyncClient(
                    timeout=timeout,
                    trust_env=False,
                )
            ) as client:

                response = (
                    await client.post(
                        tool.endpoint,
                        json=arguments,
                    )
                )

                if (
                    response.status_code
                    // 100
                    != 2
                ):
                    kind = (
                        ToolErrorType
                        .UNAVAILABLE

                        if (
                            response
                            .status_code
                            >= 500
                        )

                        else (
                            ToolErrorType
                            .EXECUTION_FAILED
                        )
                    )

                    raise ToolError(
                        kind,
                        (
                            "HTTP tool returned "
                            f"{response.status_code}"
                        ),
                    )

                return (
                    response.json()
                )

        except (
            httpx.TimeoutException,
            asyncio.TimeoutError,
        ) as exc:
            raise ToolError(
                ToolErrorType.TIMEOUT,
                "tool timed out",
            ) from exc

        except (
            httpx.RequestError
        ) as exc:
            raise ToolError(
                ToolErrorType
                .UNAVAILABLE,

                "tool unavailable",
            ) from exc

        except ValueError as exc:
            raise ToolError(
                ToolErrorType
                .EXECUTION_FAILED,

                (
                    "tool returned "
                    "invalid JSON"
                ),
            ) from exc


def _matches_json_type(value: Any, expected: str) -> bool:
    if expected == "string":
        return isinstance(value, str)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "null":
        return value is None
    return True


def _validate_arguments_against_schema(
    arguments: dict[str, Any],
    schema: dict[str, Any],
) -> None:
    """Validate the JSON-schema subset used by AgentMesh Tool contracts.

    This intentionally supports the common object/required/property/type subset
    without adding a heavyweight runtime dependency. The model is untrusted;
    Tool handlers should never receive arguments that obviously violate their
    declared contract.
    """
    if not schema:
        return

    expected_root = schema.get("type")
    if expected_root not in (None, "object"):
        raise ToolError(
            ToolErrorType.INVALID_ARGUMENTS,
            "tool input schema root must be an object",
        )

    required = schema.get("required") or []
    if isinstance(required, list):
        missing = [
            str(name)
            for name in required
            if str(name) not in arguments
        ]
        if missing:
            raise ToolError(
                ToolErrorType.INVALID_ARGUMENTS,
                "missing required arguments: " + ", ".join(missing),
            )

    properties = schema.get("properties") or {}
    if not isinstance(properties, dict):
        return

    if schema.get("additionalProperties") is False:
        unexpected = sorted(set(arguments) - set(properties))
        if unexpected:
            raise ToolError(
                ToolErrorType.INVALID_ARGUMENTS,
                "unexpected arguments: " + ", ".join(unexpected),
            )

    for name, value in arguments.items():
        spec = properties.get(name)
        if not isinstance(spec, dict):
            continue
        expected = spec.get("type")
        if isinstance(expected, str) and not _matches_json_type(value, expected):
            raise ToolError(
                ToolErrorType.INVALID_ARGUMENTS,
                f"argument {name} must be {expected}",
            )

        if isinstance(value, str):
            minimum = spec.get("minLength")
            maximum = spec.get("maxLength")
            if isinstance(minimum, int) and len(value) < minimum:
                raise ToolError(
                    ToolErrorType.INVALID_ARGUMENTS,
                    f"argument {name} is too short",
                )
            if isinstance(maximum, int) and len(value) > maximum:
                raise ToolError(
                    ToolErrorType.INVALID_ARGUMENTS,
                    f"argument {name} is too long",
                )


class ToolRegistry:
    """
    ToolRegistry 是 Tool Execution
    的最终安全边界。

    即使 ToolLoop 在调用之前
    已经做过 Governance 检查，
    execute() 仍然必须再次检查。

    原因：

        ToolLoop 并不是唯一调用方。

        LangGraph
        MCP Adapter
        future workflow
        unit test
        other runtime

    都可能直接调用 Registry。

    所以安全检查必须放在
    最靠近真正执行的位置。
    """

    def __init__(
        self,
        *,
        timeout: float = 8.0,
        governance: (
            ToolGovernancePolicy
            | None
        ) = None,
    ):
        self.timeout = (
            timeout
        )

        self._tools: dict[
            str,
            ToolDefinition,
        ] = {}

        self._adapters: dict[
            str,
            Any,
        ] = {}

        self.governance = (
            governance
            or ToolGovernancePolicy()
        )

    def register(
        self,
        tool: ToolDefinition,
        handler: (
            InternalHandler
            | None
        ) = None,
        adapter: (
            Any
            | None
        ) = None,
    ) -> None:

        if (
            tool.protocol
            == "internal"
            and handler
            is None
        ):
            raise ValueError(
                (
                    "internal tool handler "
                    "is required"
                )
            )

        if (
            tool.protocol
            == "mcp"
            and adapter
            is None
        ):
            raise ValueError(
                (
                    "MCP tool adapter "
                    "is required"
                )
            )

        self._tools[
            tool.name
        ] = tool

        self._adapters[
            tool.name
        ] = (
            adapter
            or (
                InternalToolAdapter(
                    handler
                )
                if handler
                else HTTPToolAdapter()
            )
        )

    def get(
        self,
        name: str,
    ) -> ToolDefinition:

        if (
            name
            not in self._tools
        ):
            raise ToolError(
                ToolErrorType
                .NOT_FOUND,

                (
                    "tool not found: "
                    f"{name}"
                ),
            )

        return (
            self._tools[
                name
            ]
        )

    def list(
        self,
    ) -> list[
        ToolDefinition
    ]:
        return list(
            self._tools.values()
        )

    # =====================================================
    # Governance Boundary
    # =====================================================

    def authorize(
        self,
        name: str,
        *,
        approved_tools: (
            set[str]
            | frozenset[str]
            | None
        ) = None,
    ) -> ToolDefinition:
        """
        只执行 Governance 检查，
        不真正调用 Tool。

        ToolLoop 可以先调用 authorize()
        决定是否应该发出：

            Tool Started

        避免一个被阻断的 Tool
        被错误计入真实 Tool Calls。
        """

        tool = self.get(
            name
        )

        approved = (
            tool.name
            in (
                approved_tools
                or set()
            )
        )

        decision = (
            self.governance
            .evaluate(
                tool,
                approved=approved,
            )
        )

        if not decision.allowed:
            raise ToolError(
                (
                    decision.error_type
                    or ToolErrorType
                    .PERMISSION_DENIED
                ),

                decision.reason,
            )

        return tool

    # =====================================================
    # Execution
    # =====================================================

    async def execute(
        self,
        name: str,
        arguments: dict[
            str,
            Any,
        ],
        *,
        approved_tools: (
            set[str]
            | frozenset[str]
            | None
        ) = None,
    ) -> Any:

        # -------------------------------------------------
        # Final safety check.
        # -------------------------------------------------

        tool = self.authorize(
            name,
            approved_tools=(
                approved_tools
            ),
        )

        if not isinstance(
            arguments,
            dict,
        ):
            raise ToolError(
                ToolErrorType
                .INVALID_ARGUMENTS,

                (
                    "arguments must "
                    "be an object"
                ),
            )

        _validate_arguments_against_schema(
            arguments,
            tool.input_schema,
        )

        try:
            return (
                await asyncio.wait_for(
                    self._adapters[
                        name
                    ].execute(
                        tool,
                        arguments,
                        self.timeout,
                    ),
                    self.timeout,
                )
            )

        except ToolError:
            raise

        except (
            asyncio.TimeoutError,
            TimeoutError,
        ) as exc:
            raise ToolError(
                ToolErrorType
                .TIMEOUT,

                "tool timed out",
            ) from exc

        except (
            TypeError,
            ValueError,
        ) as exc:
            raise ToolError(
                ToolErrorType
                .INVALID_ARGUMENTS,

                str(exc),
            ) from exc

        except Exception as exc:
            raise ToolError(
                ToolErrorType
                .EXECUTION_FAILED,

                str(exc),
            ) from exc