from __future__ import annotations

from typing import Any, Literal, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from app.agents import AgentExecutionRequest
from app.config import settings
from app.eval import EvaluationRequest, HeuristicEvaluator
from app.models import ModelGateway, ModelInputAttachment
from app.models.gateway import ModelEventHandler
from app.eval.repair import RepairPromptBuilder
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
    quality_score: float
    evaluation_signals: dict[str, Any]
    repair_count: int


class LangGraphAgentContext(TypedDict):
    request: AgentExecutionRequest


class LangGraphAgentWorkflow:
    """Bounded LangGraph workflow for a single complex Agent.

    The platform-level multi-Agent DAG remains outside LangGraph.  This graph is
    intentionally scoped to one Agent execution and adds a model-only
    reason/evaluate/repair loop without replaying tool actions for quality.
    """

    def __init__(
        self,
        model: AgentModelRuntime,
    ) -> None:
        self._model = model
        self._evaluator = HeuristicEvaluator()
        self._repair_builder = RepairPromptBuilder()
        self._graph = self._build_graph()

    async def run(
        self,
        request: AgentExecutionRequest,
    ) -> str:
        initial_state: LangGraphAgentState = {
            "prompt": self._build_prompt(request),
            "route": "model",
            "result": "",
            "quality_score": 0.0,
            "evaluation_signals": {},
            "repair_count": 0,
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
            runtime: Runtime[LangGraphAgentContext],
        ) -> dict:
            request = self._get_request(runtime)
            self._emit(request, "LangGraph Node Started", "running", node="prepare")

            has_tools = (
                request.tool_registry is not None
                and bool(request.tool_registry.list())
            )
            route: Literal["model", "tool"] = "tool" if has_tools else "model"

            self._emit(
                request,
                "LangGraph Route Selected",
                "completed",
                route=route,
                qualityRepairEnabled=(route == "model" and settings.langgraph_max_repairs > 0),
            )
            self._emit(request, "LangGraph Node Completed", "completed", node="prepare")
            return {"route": route}

        async def model_call(
            state: LangGraphAgentState,
            runtime: Runtime[LangGraphAgentContext],
        ) -> dict:
            request = self._get_request(runtime)
            self._emit(
                request,
                "LangGraph Node Started",
                "running",
                node="model_call",
                repairAttempt=state["repair_count"],
            )

            try:
                model = request.model_runtime or self._model
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
                self._emit(request, "LangGraph Node Failed", "error", node="model_call")
                raise

            self._emit(request, "LangGraph Node Completed", "completed", node="model_call")
            return {"result": result}

        async def tool_loop(
            state: LangGraphAgentState,
            runtime: Runtime[LangGraphAgentContext],
        ) -> dict:
            request = self._get_request(runtime)
            self._emit(request, "LangGraph Node Started", "running", node="tool_loop")

            if request.tool_registry is None:
                self._emit(request, "LangGraph Node Failed", "error", node="tool_loop")
                raise RuntimeError("tool registry is required for tool route")

            try:
                model = request.model_runtime or self._model
                result = await ToolLoopRunner(
                    model.gateway,
                    model.model,
                    request.tool_registry,
                    settings.max_tool_iterations,
                    max_retries=settings.tool_max_retries,
                    retry_backoff_seconds=settings.tool_retry_backoff_seconds,
                    vision_model=getattr(model, "vision_model", None),
                    desktop_max_iterations=settings.desktop_max_tool_iterations,
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
                self._emit(request, "LangGraph Node Failed", "error", node="tool_loop")
                raise

            self._emit(request, "LangGraph Node Completed", "completed", node="tool_loop")
            return {"result": result}

        async def evaluate(
            state: LangGraphAgentState,
            runtime: Runtime[LangGraphAgentContext],
        ) -> dict:
            request = self._get_request(runtime)
            self._emit(request, "LangGraph Node Started", "running", node="evaluate")

            evaluation = await self._evaluator.evaluate(
                EvaluationRequest(
                    task=request.task,
                    capability=request.capability,
                    result=state["result"],
                    agent_name=request.agent.name,
                )
            )
            self._emit(
                request,
                "LangGraph Quality Evaluated",
                "completed",
                node="evaluate",
                qualityScore=evaluation.quality_score,
                threshold=settings.langgraph_quality_threshold,
                signals=evaluation.signals,
            )
            return {
                "quality_score": evaluation.quality_score,
                "evaluation_signals": dict(evaluation.signals),
            }

        async def repair(
            state: LangGraphAgentState,
            runtime: Runtime[LangGraphAgentContext],
        ) -> dict:
            request = self._get_request(runtime)
            next_attempt = state["repair_count"] + 1
            self._emit(
                request,
                "LangGraph Repair Started",
                "running",
                node="repair",
                attempt=next_attempt,
            )

            # Reconstruct a tiny EvaluationResult-compatible object through the
            # deterministic evaluator output already stored in graph state.
            from app.eval.contracts import EvaluationResult

            prompt = self._repair_builder.build(
                original_task=self._build_prompt(request),
                previous_result=state["result"],
                evaluation=EvaluationResult(
                    quality_score=state["quality_score"],
                    evaluator="langgraph_workflow",
                    signals=dict(state["evaluation_signals"]),
                ),
                attempt=next_attempt,
            )
            self._emit(
                request,
                "LangGraph Repair Prepared",
                "completed",
                node="repair",
                attempt=next_attempt,
            )
            return {
                "prompt": prompt,
                "repair_count": next_attempt,
            }

        def select_route(
            state: LangGraphAgentState,
        ) -> Literal["model_call", "tool_loop"]:
            return "tool_loop" if state["route"] == "tool" else "model_call"

        def select_after_evaluation(
            state: LangGraphAgentState,
        ) -> Literal["repair", "finish"]:
            # Tool routes are never replayed solely for answer-quality recovery:
            # the tool may have performed an external side effect.
            if state["route"] != "model":
                return "finish"
            if state["quality_score"] >= settings.langgraph_quality_threshold:
                return "finish"
            if state["repair_count"] >= max(0, settings.langgraph_max_repairs):
                return "finish"
            return "repair"

        builder = StateGraph(
            LangGraphAgentState,
            context_schema=LangGraphAgentContext,
        )
        builder.add_node("prepare", prepare)
        builder.add_node("model_call", model_call)
        builder.add_node("tool_loop", tool_loop)
        builder.add_node("evaluate", evaluate)
        builder.add_node("repair", repair)

        builder.add_edge(START, "prepare")
        builder.add_conditional_edges(
            "prepare",
            select_route,
            {
                "model_call": "model_call",
                "tool_loop": "tool_loop",
            },
        )
        builder.add_edge("model_call", "evaluate")
        builder.add_edge("tool_loop", "evaluate")
        builder.add_conditional_edges(
            "evaluate",
            select_after_evaluation,
            {
                "repair": "repair",
                "finish": END,
            },
        )
        builder.add_edge("repair", "model_call")

        return builder.compile()

    @staticmethod
    def _get_request(
        runtime: Runtime[LangGraphAgentContext],
    ) -> AgentExecutionRequest:
        if runtime.context is None:
            raise RuntimeError("LangGraph runtime context is missing")
        return runtime.context["request"]

    @staticmethod
    def _build_prompt(
        request: AgentExecutionRequest,
    ) -> str:
        return (
            f"Agent={request.agent.name}; capability={request.capability}.\n"
            "Only handle your assigned subtask. "
            f"Task: {request.task}"
        )

    @staticmethod
    def _emit(
        request: AgentExecutionRequest,
        title: str,
        status: str,
        **detail: Any,
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
