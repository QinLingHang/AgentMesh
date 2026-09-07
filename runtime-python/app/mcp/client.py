import asyncio
from typing import Any
from mcp import Client
from app.mcp.contracts import MCPServerDefinition
from app.mcp.errors import MCPErrorType, MCPRuntimeError, normalize_mcp_error

class AgentMeshMCPClient:
    def __init__(self, definition: MCPServerDefinition, target: Any | None=None):
        self.definition=definition; self.target=target; self.client: Client | None=None
    async def __aenter__(self):
        if self.definition.transport=="stdio" and self.target is None:
            raise MCPRuntimeError(MCPErrorType.UNSUPPORTED_TRANSPORT,"stdio is restricted to trusted code allowlist")
        if self.definition.transport not in {"streamable_http","stdio"}:
            raise MCPRuntimeError(MCPErrorType.UNSUPPORTED_TRANSPORT,self.definition.transport)
        target=self.target if self.target is not None else self.definition.endpoint
        try:
            self.client=Client(target,read_timeout_seconds=self.definition.call_timeout_ms/1000)
            await asyncio.wait_for(self.client.__aenter__(),self.definition.connect_timeout_ms/1000)
            return self
        except asyncio.CancelledError: raise
        except asyncio.TimeoutError as exc: raise MCPRuntimeError(MCPErrorType.TIMEOUT,"MCP connect timed out") from exc
        except Exception as exc: raise normalize_mcp_error(exc,"connect") from exc
    async def __aexit__(self,*args):
        if self.client is not None: await self.client.__aexit__(*args)
    async def list_tools(self):
        try: return (await self.client.list_tools()).tools
        except asyncio.CancelledError: raise
        except asyncio.TimeoutError as exc: raise MCPRuntimeError(MCPErrorType.TIMEOUT,"MCP discovery timed out") from exc
        except Exception as exc: raise normalize_mcp_error(exc,"discovery") from exc
    async def call_tool(self,name:str,arguments:dict[str,Any]):
        try: return await asyncio.wait_for(self.client.call_tool(name,arguments,read_timeout_seconds=self.definition.call_timeout_ms/1000),self.definition.call_timeout_ms/1000)
        except asyncio.CancelledError: raise
        except asyncio.TimeoutError as exc: raise MCPRuntimeError(MCPErrorType.TIMEOUT,"MCP tool call timed out") from exc
        except MCPRuntimeError: raise
        except Exception as exc:
            error=normalize_mcp_error(exc,"tool call")
            if error.error_type==MCPErrorType.UNKNOWN:error=MCPRuntimeError(MCPErrorType.CALL_FAILED,str(error))
            raise error from exc
