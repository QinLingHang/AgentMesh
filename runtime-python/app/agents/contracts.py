from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, TYPE_CHECKING, runtime_checkable

from app.schemas import AgentProfile
from app.models.contracts import ModelInputAttachment

if TYPE_CHECKING:
    from app.tools import ToolRegistry
    from app.models.runtime import (
        ResolvedModelRuntime,
    )


ModelEventHandler = Callable[[dict[str, Any]], None]
ToolEventHandler = Callable[[dict[str, Any]], None]
RuntimeEventHandler = Callable[[dict[str, Any]],None,]


@dataclass(slots=True)
class AgentExecutionRequest:
    agent: AgentProfile
    capability: str
    task: str

    on_model_event: (
        ModelEventHandler | None
    ) = None

    tool_registry: (
        ToolRegistry | None
    ) = None

    on_tool_event: (
        ToolEventHandler | None
    ) = None

    on_runtime_event: (
        RuntimeEventHandler | None
    ) = None

    model_runtime: (
        ResolvedModelRuntime | None
    ) = None

    attachments: list[ModelInputAttachment] = field(default_factory=list)

    # P37 harness unification: when AUTO_REPAIR owns tool retries inside the
    # Guarded Tool Executor, the legacy ToolLoopRunner retry is disabled for
    # this request so one action can only be triggered by one policy. None
    # keeps the settings.tool_max_retries default.
    tool_max_retries: int | None = None

@dataclass(slots=True)
class AgentExecutionResult:
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class AgentExecutor(Protocol):
    async def execute(
        self,
        request: AgentExecutionRequest,
    ) -> AgentExecutionResult:
        ...