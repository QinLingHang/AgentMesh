from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]


class ModelMessage(BaseModel):
    role: Literal[
        "system",
        "user",
        "assistant",
        "tool",
    ]

    content: str

    tool_call_id: str | None = None

    tool_calls: list[ToolCall] = Field(
        default_factory=list
    )


class ModelTool(BaseModel):
    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(
        default_factory=dict
    )


class ModelInputAttachment(BaseModel):
    name: str
    media_type: str
    content_base64: str


class ModelRequest(BaseModel):
    model: str
    messages: list[ModelMessage]

    temperature: float | None = None

    max_tokens: int | None = Field(
        default=None,
        gt=0,
    )

    timeout: float | None = Field(
        default=None,
        gt=0,
    )

    tools: list[ModelTool] = Field(
        default_factory=list
    )

    attachments: list[ModelInputAttachment] = Field(
        default_factory=list
    )


class ModelResponse(BaseModel):
    content: str
    provider: str
    model: str

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0

    finish_reason: str | None = None

    estimated_cost: float | None = None

    tool_calls: list[ToolCall] = Field(
        default_factory=list
    )


class ModelProvider(Protocol):
    name: str

    async def generate(
        self,
        request: ModelRequest,
    ) -> ModelResponse:
        ...