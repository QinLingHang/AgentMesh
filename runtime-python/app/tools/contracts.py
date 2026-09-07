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