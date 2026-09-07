import json
import re
from typing import Any
from app.mcp.contracts import MCPServerDefinition
from app.mcp.errors import MCPErrorType, MCPRuntimeError
from app.tools.contracts import ToolDefinition


def _slug(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_]+", "_", value.strip().lower()).strip("_")
    return value[:40] or "server"


def model_tool_name(server: MCPServerDefinition, original: str) -> str:
    return f"mcp_{server.id}_{_slug(server.name)}_{_slug(original)}"[:64]


def _infer_mcp_risk(name: str, description: str) -> tuple[str, bool]:
    """Fail-safe default risk classification for discovered MCP tools.

    MCP does not standardize an execution-risk field. AgentMesh therefore
    classifies obvious mutation/destructive actions before exposing them to the
    model. Administrators can later replace this heuristic with a richer MCP
    policy registry without changing the execution contract.
    """
    text = f"{name} {description}".lower()
    destructive = (
        "delete", "remove", "destroy", "drop", "refund", "cancel",
        "terminate", "revoke", "charge", "pay", "purchase", "transfer",
    )
    mutating = (
        "create", "update", "modify", "write", "set_", "send", "publish",
        "submit", "approve", "reject", "book", "reserve", "schedule",
    )
    if any(word in text for word in destructive):
        return "high", True
    if any(word in text for word in mutating):
        return "medium", True
    return "low", False


def map_mcp_tool(server: MCPServerDefinition, tool: Any) -> ToolDefinition:
    original = str(tool.name)
    description = str(tool.description or "")
    risk_level, requires_confirmation = _infer_mcp_risk(original, description)
    return ToolDefinition(
        name=model_tool_name(server, original),
        description=description,
        protocol="mcp",
        endpoint=server.endpoint,
        input_schema=dict(tool.input_schema or {}),
        enabled=server.enabled,
        mcp_server_id=server.id,
        original_tool_name=original,
        risk_level=risk_level,
        requires_confirmation=requires_confirmation,
        metadata={
            "source": "mcp",
            "server_name": server.name,
            "transport": server.transport,
            "risk_source": "agentmesh_heuristic",
        },
    )


def convert_call_result(result: Any) -> Any:
    if bool(getattr(result, "is_error", False)):
        raise MCPRuntimeError(MCPErrorType.CALL_FAILED, "MCP tool returned is_error=true")
    structured = getattr(result, "structured_content", None)
    if structured is not None:
        return structured
    blocks = []
    for block in getattr(result, "content", []) or []:
        if getattr(block, "type", None) == "text":
            blocks.append(str(block.text))
        elif hasattr(block, "model_dump"):
            blocks.append(block.model_dump(mode="json", by_alias=True, exclude_none=True))
    if not blocks:
        raise MCPRuntimeError(MCPErrorType.INVALID_RESULT, "MCP tool returned no usable content")
    return blocks[0] if len(blocks) == 1 else blocks
