import asyncio

import httpx

from app.agents import (
    A2AAgentExecutor,
    AgentExecutionRequest,
    AgentExecutionResult,
)
from app.agents.workflows import (
    LangGraphAgentWorkflow,
)
from app.config import settings
from app.kernel import (
    AgentMeshPlugin,
    PluginKind,
    PluginManifest,
    RuntimeContext,
)
from app.tools import (
    ToolLoopRunner,
)


# =========================================================
# Internal Agent
# =========================================================


class InternalAgentPlugin(
    AgentMeshPlugin
):
    manifest = PluginManifest(
        "agent.internal",
        "Internal Agent Executor",
        "0.3.0",
        PluginKind.AGENT,
    )

    def __init__(
        self,
    ) -> None:
        self.context: (
            RuntimeContext
            | None
        ) = None

    async def setup(
        self,
        context: RuntimeContext,
    ) -> None:
        self.context = (
            context
        )

    async def execute(
        self,
        request: AgentExecutionRequest,
    ) -> AgentExecutionResult:
        agent = (
            request.agent
        )

        if (
            agent.endpoint
            .startswith(
                "internal://fail/"
            )
        ):
            await asyncio.sleep(
                0.08
            )

            raise TimeoutError(
                (
                    "simulated timeout "
                    f"from {agent.name}"
                )
            )

        if self.context is None:
            raise RuntimeError(
                "plugin not initialized"
            )

        model = (
            request.model_runtime
            or self.context.get(
                "model.default"
            )
        )

        prompt = (
            f"Agent={agent.name}; "
            f"capability="
            f"{request.capability}.\n"
            "Only handle your "
            "assigned subtask. "
            f"Task: {request.task}"
        )

        if (
            request.tool_registry
            is not None
            and
            request.tool_registry
            .list()
        ):
            content = (
                await ToolLoopRunner(
                    model.gateway,
                    model.model,
                    request
                    .tool_registry,
                    settings
                    .max_tool_iterations,
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
                )
                .run(
                    prompt,
                    request
                    .on_model_event,
                    request
                    .on_tool_event,
                    attachments=request.attachments,
                )
            )

            return (
                AgentExecutionResult(
                    content=content,
                    metadata={
                        "protocol":
                            "internal",

                        "tool_loop":
                            True,
                    },
                )
            )

        if request.attachments:
            content = await model.generate(
                prompt,
                request.on_model_event,
                attachments=request.attachments,
            )
        else:
            content = await model.generate(
                prompt,
                request.on_model_event,
            )

        return (
            AgentExecutionResult(
                content=content,
                metadata={
                    "protocol":
                        "internal",

                    "tool_loop":
                        False,
                },
            )
        )


# =========================================================
# Private HTTP Agent
# =========================================================


class HTTPAgentPlugin(
    AgentMeshPlugin
):
    manifest = PluginManifest(
        "agent.http",
        "HTTP Agent Adapter",
        "0.3.0",
        PluginKind.AGENT,
    )

    async def setup(
        self,
        context: RuntimeContext,
    ) -> None:
        self.context = (
            context
        )

    async def execute(
        self,
        request: AgentExecutionRequest,
    ) -> AgentExecutionResult:
        agent = (
            request.agent
        )

        async with (
            httpx.AsyncClient(
                timeout=(
                    settings
                    .http_agent_timeout_seconds
                ),
                trust_env=False,
            )
        ) as client:
            response = (
                await client.post(
                    agent.endpoint,
                    json={
                        "task":
                            request.task,

                        "capability":
                            request
                            .capability,

                        "agentName":
                            agent.name,
                    },
                )
            )

            response.raise_for_status()

            data = (
                response.json()
            )

            content = str(
                data.get(
                    "answer"
                )
                or data.get(
                    "result"
                )
                or data
            )

            return (
                AgentExecutionResult(
                    content=content,
                    metadata={
                        "protocol":
                            "http",

                        "status_code":
                            response
                            .status_code,
                    },
                )
            )


# =========================================================
# LangGraph Agent
# =========================================================


class LangGraphAgentPlugin(
    AgentMeshPlugin
):
    manifest = PluginManifest(
        "agent.langgraph",
        (
            "LangGraph "
            "Agent Executor"
        ),
        "0.3.0",
        PluginKind.AGENT,
    )

    def __init__(
        self,
    ) -> None:
        self.context: (
            RuntimeContext
            | None
        ) = None

        self.workflow: (
            LangGraphAgentWorkflow
            | None
        ) = None

    async def setup(
        self,
        context: RuntimeContext,
    ) -> None:
        self.context = (
            context
        )

        model = (
            context.get(
                "model.default"
            )
        )

        self.workflow = (
            LangGraphAgentWorkflow(
                model
            )
        )

    async def execute(
        self,
        request: AgentExecutionRequest,
    ) -> AgentExecutionResult:

        if self.workflow is None:
            raise RuntimeError(
                (
                    "LangGraph agent "
                    "plugin is not "
                    "initialized"
                )
            )

        content = (
            await self
            .workflow
            .run(
                request
            )
        )

        return (
            AgentExecutionResult(
                content=content,
                metadata={
                    "protocol":
                        "langgraph",

                    "workflow":
                        "stategraph",
                },
            )
        )


# =========================================================
# A2A Agent
# =========================================================


class A2AAgentPlugin(
    AgentMeshPlugin
):
    """
    Plugin wrapper around A2AAgentExecutor.

    RuntimeEngine only resolves:

        protocol=a2a
            ↓
        agent.a2a

    It does not need to know:
        Agent Card
        A2A transport
        Message
        Task
        Artifact
    """

    manifest = PluginManifest(
        "agent.a2a",
        "A2A Agent Adapter",
        "0.1.0",
        PluginKind.AGENT,
    )

    def __init__(
        self,
    ) -> None:
        self.context: (
            RuntimeContext
            | None
        ) = None

        self.executor = (
            A2AAgentExecutor(
                timeout_seconds=(
                    settings
                    .a2a_timeout_seconds
                ),

                trust_env=(
                    settings
                    .a2a_http_trust_env
                ),

                streaming=(
                    settings
                    .a2a_streaming
                ),
            )
        )

    async def setup(
        self,
        context: RuntimeContext,
    ) -> None:
        self.context = (
            context
        )

    async def execute(
        self,
        request: AgentExecutionRequest,
    ) -> AgentExecutionResult:

        return (
            await self
            .executor
            .execute(
                request
            )
        )
    async def resume(
        self,
        request: AgentExecutionRequest,
        *,
        task_id: str,
        context_id: str,
    ) -> AgentExecutionResult:

        return (
            await self
            .executor
            .resume(
                request,

                task_id=(
                    task_id
                ),

                context_id=(
                    context_id
                ),
            )
        )
