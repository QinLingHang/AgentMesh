from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

from app.tools.contracts import ToolDefinition


SENSITIVE_KEYS = (
    "authorization",
    "api_key",
    "apikey",
    "password",
    "token",
    "secret",
    "credential",
    "otp",
)


def canonical_arguments(arguments: dict[str, Any]) -> str:
    return json.dumps(
        arguments,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def tool_call_fingerprint(
    tool: ToolDefinition,
    arguments: dict[str, Any],
) -> str:
    """Create a stable fingerprint for the exact action being approved.

    The fingerprint intentionally binds the approval to both the current tool
    identity/configuration and the canonical arguments selected by the model.
    If either changes before resume, execution is denied rather than silently
    approving a different action.
    """
    payload = {
        "id": tool.id,
        "name": tool.name,
        "protocol": tool.protocol,
        "endpoint": tool.endpoint or "",
        "mcpServerId": tool.mcp_server_id,
        "originalToolName": tool.original_tool_name or "",
        "riskLevel": tool.risk_level,
        "requiresConfirmation": bool(tool.requires_confirmation),
        "arguments": arguments,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _safe_preview_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: (
                "[REDACTED]"
                if any(marker in key.lower() for marker in SENSITIVE_KEYS)
                else _safe_preview_value(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_safe_preview_value(item) for item in value[:12]]
    if isinstance(value, str):
        lower = value.lower()
        if any(
            marker in lower
            for marker in (
                "password=", "password:", "token=", "token:",
                "credential=", "credential:", "otp=", "otp:",
                "authorization:", "bearer ",
            )
        ):
            return "[REDACTED]"
        if len(value) > 160:
            return value[:160] + "…"
        return value
    return value


@dataclass(frozen=True, slots=True)
class ToolApprovalRequest:
    approval_id: str
    tool_name: str
    protocol: str
    risk_level: str
    requires_confirmation: bool
    arguments: dict[str, Any]
    fingerprint: str
    summary: str

    @classmethod
    def create(
        cls,
        tool: ToolDefinition,
        arguments: dict[str, Any],
    ) -> "ToolApprovalRequest":
        approval_id = str(uuid.uuid4())
        fingerprint = tool_call_fingerprint(tool, arguments)
        summary = (
            f"将执行工具“{tool.name}”。"
            f"风险等级：{tool.risk_level}。"
        )
        return cls(
            approval_id=approval_id,
            tool_name=tool.name,
            protocol=tool.protocol,
            risk_level=tool.risk_level,
            requires_confirmation=bool(tool.requires_confirmation),
            arguments=dict(arguments),
            fingerprint=fingerprint,
            summary=summary,
        )

    def safe_arguments(self) -> dict[str, Any]:
        return _safe_preview_value(self.arguments)


class ToolApprovalRequired(RuntimeError):
    """Control-flow signal: a tool call is ready but needs human approval."""

    def __init__(self, request: ToolApprovalRequest):
        super().__init__(request.summary)
        self.request = request
