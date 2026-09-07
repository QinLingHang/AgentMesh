from enum import Enum

class MCPErrorType(str, Enum):
    CONNECTION_FAILED="connection_failed"; TIMEOUT="timeout"; PROTOCOL_ERROR="protocol_error"
    TOOL_NOT_FOUND="tool_not_found"; CALL_FAILED="call_failed"; INVALID_RESULT="invalid_result"
    UNAVAILABLE="unavailable"; UNSUPPORTED_TRANSPORT="unsupported_transport"; UNKNOWN="unknown"

class MCPRuntimeError(RuntimeError):
    def __init__(self, error_type: MCPErrorType, message: str):
        super().__init__(message); self.error_type=error_type

def _leaves(exc: BaseException):
    if isinstance(exc,BaseExceptionGroup):
        for child in exc.exceptions: yield from _leaves(child)
    else: yield exc

def normalize_mcp_error(exc: BaseException,operation: str) -> MCPRuntimeError:
    """Flatten AnyIO exception groups and retain the actionable SDK/transport cause."""
    leaves=list(_leaves(exc))
    for leaf in leaves:
        if isinstance(leaf,(TimeoutError,)) or "timeout" in type(leaf).__name__.lower():
            return MCPRuntimeError(MCPErrorType.TIMEOUT,f"MCP {operation} timed out")
    for leaf in leaves:
        name=type(leaf).__name__.lower();message=str(leaf)
        if "connect" in name or "connection" in name:
            return MCPRuntimeError(MCPErrorType.CONNECTION_FAILED,f"MCP {operation} connection failed: {message}")
        if name in {"mcperror","mcp_error"} or hasattr(leaf,"code"):
            return MCPRuntimeError(MCPErrorType.PROTOCOL_ERROR,f"MCP {operation} protocol error: {message}")
    detail=str(leaves[0]) if leaves else str(exc)
    return MCPRuntimeError(MCPErrorType.UNKNOWN,f"MCP {operation} failed: {detail}")
