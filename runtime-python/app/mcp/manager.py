import asyncio
import time
from contextlib import AsyncExitStack
from typing import Any, Callable
from app.mcp.client import AgentMeshMCPClient
from app.mcp.contracts import MCPServerDefinition
from app.mcp.errors import MCPErrorType, MCPRuntimeError
from app.mcp.mapper import convert_call_result, map_mcp_tool
from app.tools.contracts import ToolDefinition, ToolError, ToolErrorType

MCPEventHandler=Callable[[dict[str,Any]],None]

class MCPToolAdapter:
    def __init__(self,manager:"MCPManager"): self.manager=manager
    async def execute(self,tool:ToolDefinition,arguments:dict[str,Any],timeout:float)->Any:
        try: return await self.manager.call_tool(tool,arguments)
        except MCPRuntimeError as exc:
            mapping={MCPErrorType.TIMEOUT:ToolErrorType.TIMEOUT,MCPErrorType.TOOL_NOT_FOUND:ToolErrorType.NOT_FOUND,
                MCPErrorType.CONNECTION_FAILED:ToolErrorType.UNAVAILABLE,MCPErrorType.UNAVAILABLE:ToolErrorType.UNAVAILABLE}
            raise ToolError(mapping.get(exc.error_type,ToolErrorType.EXECUTION_FAILED),str(exc)) from exc

class MCPManager:
    def __init__(self,servers:list[MCPServerDefinition],on_event:MCPEventHandler|None=None,targets:dict[int,Any]|None=None):
        self.servers={s.id:s for s in servers if s.enabled};self.on_event=on_event;self.targets=targets or {};self.stack=AsyncExitStack();self.clients={}
    async def __aenter__(self): await self.stack.__aenter__();return self
    async def __aexit__(self,*args): return await self.stack.__aexit__(*args)
    def _emit(self,title,status,server,started,**detail):
        if self.on_event:self.on_event({"title":title,"status":status,"server":server.name,"transport":server.transport,"latency_ms":int((time.perf_counter()-started)*1000),**detail})
    async def _client(self,server:MCPServerDefinition):
        if server.id not in self.clients:
            self.clients[server.id]=await self.stack.enter_async_context(AgentMeshMCPClient(server,self.targets.get(server.id)))
        return self.clients[server.id]
    async def discover(self,server:MCPServerDefinition)->list[ToolDefinition]:
        if server.id not in self.servers: raise MCPRuntimeError(MCPErrorType.UNAVAILABLE,"MCP server is outside task scope or disabled")
        started=time.perf_counter();self._emit("MCP Discovery Started","running",server,started)
        try:
            tools=[map_mcp_tool(server,t) for t in await (await self._client(server)).list_tools()]
            self._emit("MCP Discovery Completed","completed",server,started,tool_count=len(tools));return tools
        except asyncio.CancelledError: raise
        except MCPRuntimeError as exc:self._emit("MCP Discovery Failed","error",server,started,error={"type":exc.error_type.value,"message":str(exc)});raise
    async def discover_all(self)->list[ToolDefinition]:
        out=[]
        for server in self.servers.values():
            try: out.extend(await self.discover(server))
            except asyncio.CancelledError: raise
            except MCPRuntimeError: continue
        return out
    async def call_tool(self,tool:ToolDefinition,arguments:dict[str,Any])->Any:
        if tool.mcp_server_id not in self.servers: raise MCPRuntimeError(MCPErrorType.UNAVAILABLE,"MCP server is outside task scope")
        server=self.servers[tool.mcp_server_id];original=tool.original_tool_name
        if not original: raise MCPRuntimeError(MCPErrorType.TOOL_NOT_FOUND,"original MCP tool name missing")
        started=time.perf_counter();self._emit("MCP Call Started","running",server,started,tool=original)
        try:
            result=convert_call_result(await (await self._client(server)).call_tool(original,arguments))
            self._emit("MCP Call Completed","completed",server,started,tool=original);return result
        except asyncio.CancelledError: raise
        except MCPRuntimeError as exc:self._emit("MCP Call Failed","error",server,started,tool=original,error={"type":exc.error_type.value,"message":str(exc)});raise
