from enum import Enum
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
)


class ToolDefinition(BaseModel):
    """
    AgentMesh Tool Contract.

    同时兼容：

    Python 内部：
        input_schema
        risk_level
        requires_confirmation

    Go / React JSON：
        inputSchema
        riskLevel
        requiresConfirmation
    """

    model_config = ConfigDict(
        populate_by_name=True
    )

    id: int | None = None

    name: str

    description: str = ""

    protocol: Literal[
        "internal",
        "http",
        "mcp",
    ] = "internal"

    endpoint: str | None = None

    input_schema: dict[
        str,
        Any,
    ] = Field(
        default_factory=dict,
        alias="inputSchema",
    )

    risk_level: Literal[
        "low",
        "medium",
        "high",
    ] = Field(
        default="low",
        alias="riskLevel",
    )

    requires_confirmation: bool = Field(
        default=False,
        alias="requiresConfirmation",
    )

    enabled: bool = True

    mcp_server_id: int | None = Field(
        default=None,
        alias="mcpServerId",
    )

    original_tool_name: str | None = Field(
        default=None,
        alias="originalToolName",
    )

    metadata: dict[
        str,
        Any,
    ] = Field(
        default_factory=dict
    )

    # =====================================================
    # P37 Agent Harness extensions (§6.2)
    #
    # These optional fields complete strict output validation and the
    # side-effect-aware recovery policy. They must be threaded through
    # Python, Go, React and the database together.
    # =====================================================

    # JSON Schema that a successful response must satisfy. When absent the
    # output validation status is NOT_CONFIGURED - never recorded as PASS.
    output_schema: dict[
        str,
        Any,
    ] | None = Field(
        default=None,
        alias="outputSchema",
    )

    # READ_ONLY / IDEMPOTENT_WRITE / NON_IDEMPOTENT_WRITE decide whether an
    # automatic retry is ever allowed. Legacy tools default to UNKNOWN, which
    # never justifies an automatic write retry.
    side_effect_risk: Literal[
        "READ_ONLY",
        "IDEMPOTENT_WRITE",
        "NON_IDEMPOTENT_WRITE",
        "UNKNOWN",
    ] = Field(
        default="UNKNOWN",
        alias="sideEffectRisk",
    )

    # Whether write tools support safe replay via an idempotency key.
    supports_idempotency_key: bool = Field(
        default=False,
        alias="supportsIdempotencyKey",
    )

    # Explicit alternative tool (registry name). The harness never searches
    # for a replacement on its own.
    fallback_tool_id: str | None = Field(
        default=None,
        alias="fallbackToolId",
    )

    # Explicit argument alias mapping (alias -> canonical name). No semantic
    # guessing is performed.
    argument_aliases: dict[
        str,
        str,
    ] = Field(
        default_factory=dict,
        alias="argumentAliases",
    )


class ToolErrorType(
    str,
    Enum,
):
    NOT_FOUND = (
        "not_found"
    )

    INVALID_ARGUMENTS = (
        "invalid_arguments"
    )

    TIMEOUT = (
        "timeout"
    )

    UNAVAILABLE = (
        "unavailable"
    )

    PERMISSION_DENIED = (
        "permission_denied"
    )

    REQUIRES_APPROVAL = (
        "requires_approval"
    )

    EXECUTION_FAILED = (
        "execution_failed"
    )

    UNKNOWN = (
        "unknown"
    )


class ToolError(
    RuntimeError
):
    def __init__(
        self,
        error_type: ToolErrorType,
        message: str,
    ):
        super().__init__(
            message
        )

        self.error_type = (
            error_type
        )