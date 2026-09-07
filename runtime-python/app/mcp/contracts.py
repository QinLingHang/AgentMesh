from typing import Any, Literal
from pydantic import BaseModel, Field

class MCPServerDefinition(BaseModel):
    id: int
    name: str
    transport: Literal["streamable_http", "stdio"] = "streamable_http"
    endpoint: str = ""
    enabled: bool = True
    connect_timeout_ms: int = Field(default=5000, gt=0)
    call_timeout_ms: int = Field(default=10000, gt=0)
    trusted_stdio_name: str | None = None

class MCPDiscoverRequest(BaseModel):
    server: MCPServerDefinition

class MCPDiscoverResponse(BaseModel):
    tools: list[dict[str, Any]]
