from __future__ import annotations

from typing import Literal, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from app.agents import AgentExecutionRequest
from app.config import settings
from app.models import ModelGateway, ModelInputAttachment
from app.models.gateway import ModelEventHandler
from app.tools import ToolApprovalRequired, ToolLoopRunner


class AgentModelRuntime(Protocol):
    gateway: ModelGateway
    model: str

    async def generate(
        self,
        prompt: str,
        on_event: ModelEventHandler | None = None,
        attachments: list[ModelInputAttachment] | None = None,
    ) -> str:
        ...


class LangGraphAgentState(TypedDict):
    prompt: str
    route: Literal["model", "tool"]
    result: str


class LangGraphAgentContext(TypedDict):
    request: AgentExecutionRequest


class LangGraphAgentWorkflow:
    def __init__(
        self,
        model: AgentModelRuntime,
    ) -> None:
        self._model = model
        self._graph = self._build_graph()

    async def run(
        self,
        request: AgentExecutionRequest,
    ) -> str:
        initial_state: LangGraphAgentState = {
            "prompt": self._build_prompt(request),
            "route": "model",
            "result": "",
        }

        final_state = await self._graph.ainvoke(
            initial_state,
            context={
                "request": request,
            },
        )

        return final_state["result"]

    def _build_graph(self):
        async def prepare(
            state: LangGraphAgentState,
            runtime: Runtime[
                LangGraphAgentContext
            ],
        ) -> dict:
            request = self._get_request(
                runtime
            )

            self._emit(
                request,
                "LangGraph Node Started",
                "running",
                node="prepare",
            )

            has_tools = (
                request.tool_registry is not None
                and bool(
                    request.tool_registry.list()
                )
            )

            route = (
                "tool"
                if has_tools
                else "model"
            )

            self._emit(
                request,
                "LangGraph Route Selected",
                "completed",
                route=route,
            )

            self._emit(
                request,
                "LangGraph Node Completed",
                "completed",
                node="prepare",
            )

            return {
                "route": route,
            }

        async def model_call(
            state: LangGraphAgentState,
            runtime: Runtime[
                LangGraphAgentContext
            ],
        ) -> dict:
            request = self._get_request(
                runtime
            )

            self._emit(
                request,
                "LangGraph Node Started",
                "running",
                node="model_call",
            )

            try:
                model = (
                    request.model_runtime
                    or self._model
                )

                if request.attachments:
                    result = await model.generate(
                        state["prompt"],
                        request.on_model_event,
                        attachments=request.attachments,
                    )
                else:
                    result = await model.generate(
                        state["prompt"],
                        request.on_model_event,
                    )
            except Exception:
                self._emit(
                    request,
                    "LangGraph Node Failed",
                    "error",
                    node="model_call",
                )
                raise

            self._emit(
                request,
                "LangGraph Node Completed",
                "completed",
                node="model_call",
            )

            return {
                "result": result,
            }

        async def tool_loop(
            state: LangGraphAgentState,
            runtime: Runtime[
                LangGraphAgentContext
            ],
        ) -> dict:
            request = self._get_request(
                runtime
            )

            self._emit(
                request,
                "LangGraph Node Started",
                "running",
                node="tool_loop",
            )

            if request.tool_registry is None:
                self._emit(
                    request,
                    "LangGraph Node Failed",
                    "error",
                    node="tool_loop",
                )

                raise RuntimeError(
                    "tool registry is required "
                    "for tool route"
                )

            try:
                model = (
                    request.model_runtime
                    or self._model
                )
                result = await ToolLoopRunner(
                    model.gateway,
                    model.model,
                    request.tool_registry,
                    settings.max_tool_iterations,
                    max_retries=(
                        settings.tool_max_retries
                    ),
                    retry_backoff_seconds=(
                        settings.tool_retry_backoff_seconds
                    ),
                    vision_model=getattr(
                        model,
                        "vision_model",
                        None,
                    ),
                    desktop_max_iterations=(
                        settings.desktop_max_tool_iterations
                    ),
                ).run(
                    state["prompt"],
                    request.on_model_event,
                    request.on_tool_event,
                    attachments=request.attachments,
                )
            except ToolApprovalRequired:
                self._emit(
                    request,
                    "LangGraph Node Suspended",
                    "completed",
                    node="tool_loop",
                    reason="approval_required",
                )
                raise
            except Exception:
                self._emit(
                    request,
                    "LangGraph Node Failed",
                    "error",
                    node="tool_loop",
                )
                raise

            self._emit(
                request,
                "LangGraph Node Completed",
                "completed",
                node="tool_loop",
            )

            return {
                "result": result,
            }

        def select_route(
            state: LangGraphAgentState,
        ) -> Literal[
            "model_call",
            "tool_loop",
        ]:
            if state["route"] == "tool":
                return "tool_loop"

            return "model_call"

        builder = StateGraph(
            LangGraphAgentState,
            context_schema=LangGraphAgentContext,
        )

        builder.add_node(
            "prepare",
            prepare,
        )

        builder.add_node(
            "model_call",
            model_call,
        )

        builder.add_node(
            "tool_loop",
            tool_loop,
        )

        builder.add_edge(
            START,
            "prepare",
        )

        builder.add_conditional_edges(
            "prepare",
            select_route,
            {
                "model_call": "model_call",
                "tool_loop": "tool_loop",
            },
        )

        builder.add_edge(
            "model_call",
            END,
        )

        builder.add_edge(
            "tool_loop",
            END,
        )

        return builder.compile()

    @staticmethod
    def _get_request(
        runtime: Runtime[LangGraphAgentContext],
    ) -> AgentExecutionRequest:
        if runtime.context is None:
            raise RuntimeError(
                "LangGraph runtime context is missing"
            )

        return runtime.context["request"]

    @staticmethod
    def _build_prompt(
        request: AgentExecutionRequest,
    ) -> str:
        return (
            f"Agent={request.agent.name}; "
            f"capability={request.capability}.\n"
            "Only handle your assigned subtask. "
            f"Task: {request.task}"
        )
    @staticmethod
    def _emit(
        request: AgentExecutionRequest,
        title: str,
        status: str,
        **detail,
    ) -> None:
        if request.on_runtime_event is None:
            return

        request.on_runtime_event(
            {
                "kind": "langgraph",
                "title": title,
                "status": status,
                **detail,
            }
        )
