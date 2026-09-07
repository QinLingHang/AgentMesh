from __future__ import annotations

import os

import uvicorn

import re

from a2a.helpers import (
    get_message_text,
    new_task_from_user_message,
    new_text_message,
    new_text_part,
)
from a2a.server.agent_execution import (
    AgentExecutor,
    RequestContext,
)
from a2a.server.events import (
    EventQueue,
)
from a2a.server.request_handlers import (
    DefaultRequestHandler,
)
from a2a.server.routes import (
    create_agent_card_routes,
    create_jsonrpc_routes,
)
from a2a.server.tasks import (
    InMemoryTaskStore,
    TaskUpdater,
)
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
)
from a2a.types.a2a_pb2 import (
    TaskState,
)
from a2a.utils.constants import (
    AGENT_CARD_WELL_KNOWN_PATH,
)

from starlette.applications import (
    Starlette,
)
from starlette.requests import Request
from starlette.responses import (
    JSONResponse,
)
from starlette.routing import Route


HOST = os.getenv(
    "A2A_DEMO_HOST",
    "127.0.0.1",
)

PORT = int(
    os.getenv(
        "A2A_DEMO_PORT",
        "9591",
    )
)

PUBLIC_URL = os.getenv(
    "A2A_DEMO_PUBLIC_URL",
    f"http://127.0.0.1:{PORT}",
).rstrip("/")


# =========================================================
# Remote Agent "Brain"
#
# 这里故意不使用 AgentMesh 内部模型。
#
# 原因：
# 我们当前要验证的是：
#
#   AgentMesh
#       ↓ A2A
#   一个真正独立的黑盒 Agent
#
# 它以后完全可以替换成：
#   LangGraph
#   Java Agent
#   Go Agent
#   ADK
#   第三方 Agent
# =========================================================


def extract_order_id(
    text: str,
) -> str:

    match = re.search(
        r"\bORDER[-_A-Z0-9]*\d+\b",
        text,
        flags=re.IGNORECASE,
    )

    if match is None:
        return ""

    return match.group(0)


def remote_agent_logic(
    text: str,
) -> str:

    normalized = (
        text.strip()
    )

    order_id = (
        extract_order_id(
            normalized
        )
    )

    if order_id:

        return (
            "[Remote A2A Agent]\n"
            "已恢复之前暂停的 A2A Task。\n\n"
            f"订单号：{order_id}\n"
            "订单状态：已支付，处理中。\n\n"
            "执行结果：Resume 成功，"
            "远程 Task 已完成。"
        )

    return (
        "[Remote A2A Agent]\n"
        "我已经通过标准 A2A 协议收到 "
        "AgentMesh 分配的任务。\n\n"
        f"收到的任务：{normalized}\n\n"
        "执行结果：远程异构 Agent "
        "执行成功。"
    )


# =========================================================
# A2A Server-side Executor
# =========================================================


class DemoRemoteAgentExecutor(
    AgentExecutor
):
    """
    真正运行在 AgentMesh Runtime 之外的
    A2A Remote Agent。

    Client:
        AgentMesh

    Server:
        localhost:9591

    Contract:
        A2A v1.x
    """

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:

        # =================================================
        # 1. Obtain / create A2A Task
        # =================================================

        if context.current_task:
            task = (
                context.current_task
            )

        else:
            task = (
                new_task_from_user_message(
                    context.message
                )
            )

            await (
                event_queue
                .enqueue_event(
                    task
                )
            )

        # =================================================
        # 2. TaskUpdater
        #
        # 用于：
        # WORKING
        # Artifact
        # COMPLETED
        # =================================================

        updater = (
            TaskUpdater(
                event_queue=(
                    event_queue
                ),
                task_id=(
                    task.id
                ),
                context_id=(
                    task.context_id
                ),
            )
        )

        # =================================================
        # 3. WORKING
        # =================================================

        await updater.update_status(
            state=(
                TaskState
                .TASK_STATE_WORKING
            ),
            message=(
                new_text_message(
                    (
                        "Remote A2A Agent "
                        "正在执行任务。"
                    )
                )
            ),
        )

        # =================================================
        # 4. Read user's A2A Message
        # =================================================

        query = (
            get_message_text(
                context.message
            )
        )


                # =================================================
        # INPUT_REQUIRED Demo
        # =================================================

        normalized_query = (
            query.lower()
        )

        is_order_query = (
            "订单"
            in query
            or
            "order"
            in normalized_query
        )

        order_id = (
            extract_order_id(
                query
            )
        )

        if (
            is_order_query
            and
            not order_id
        ):

            await updater.update_status(
                state=(
                    TaskState
                    .TASK_STATE_INPUT_REQUIRED
                ),

                message=(
                    new_text_message(
                        (
                            "请提供订单号，"
                            "例如 ORDER202609030001。"
                        )
                    )
                ),
            )

            # -------------------------------------------------
            # 这里非常关键：
            #
            # INPUT_REQUIRED 以后 return。
            #
            # 它不是失败。
            #
            # Server 主动把控制权交回 Client。
            # 后续 Client 带 task_id/context_id 再发消息。
            # -------------------------------------------------

            return

        # =================================================
        # 5. Execute remote logic
        # =================================================

        result = (
            remote_agent_logic(
                query
            )
        )

        # =================================================
        # 6. Artifact
        #
        # 最终业务输出通过 Artifact 返回。
        # =================================================

        await updater.add_artifact(
            parts=[
                new_text_part(
                    text=(
                        result
                    ),
                    media_type=(
                        "text/plain"
                    ),
                )
            ]
        )

        # =================================================
        # 7. COMPLETED
        # =================================================

        await updater.update_status(
            state=(
                TaskState
                .TASK_STATE_COMPLETED
            ),
            message=(
                new_text_message(
                    (
                        "Remote A2A Agent "
                        "执行完成。"
                    )
                )
            ),
        )

    async def cancel(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:

        raise NotImplementedError(
            (
                "Demo Remote A2A Agent "
                "does not support "
                "cancellation yet."
            )
        )


# =========================================================
# Agent Card
# =========================================================


def build_agent_card() -> AgentCard:

    return AgentCard(
        name=(
            "AgentMesh Remote "
            "A2A Demo Agent"
        ),

        description=(
            "Independent remote agent "
            "used to validate AgentMesh "
            "A2A interoperability."
        ),

        version=(
            "1.0.0"
        ),

        default_input_modes=[
            "text/plain"
        ],

        default_output_modes=[
            "text/plain"
        ],

        capabilities=(
            AgentCapabilities(
                streaming=True
            )
        ),

        supported_interfaces=[
            AgentInterface(
                protocol_binding=(
                    "JSONRPC"
                ),

                url=(
                    PUBLIC_URL
                ),

                protocol_version=(
                    "1.0"
                ),
            )
        ],

            skills=[
                AgentSkill(
                    id="general",

                    name=(
                        "General Remote "
                        "Execution"
                    ),

                    description=(
                        "Execute general "
                        "tasks assigned by "
                        "AgentMesh through A2A."
                    ),

                    input_modes=[
                        "text/plain"
                    ],

                    output_modes=[
                        "text/plain"
                    ],

                    tags=[
                        "a2a",
                        "agentmesh",
                        "general",
                    ],

                    examples=[
                        (
                            "Execute this "
                            "AgentMesh subtask."
                        )
                    ],
                ),

                AgentSkill(
                    id="document",

                    name=(
                        "Document Analysis"
                    ),

                    description=(
                        "Analyze and summarize "
                        "document-related tasks."
                    ),

                    input_modes=[
                        "text/plain"
                    ],

                    output_modes=[
                        "text/plain"
                    ],

                    tags=[
                        "document",
                        "analysis",
                        "a2a",
                    ],

                    examples=[
                        (
                            "Summarize this "
                            "document."
                        )
                    ],
                ),
            ]
    )


AGENT_CARD = (
    build_agent_card()
)


# =========================================================
# Health
# =========================================================


async def health(
    request: Request,
) -> JSONResponse:

    return JSONResponse(
        {
            "status":
                "ok",

            "agent":
                AGENT_CARD.name,

            "protocol":
                "a2a",

            "version":
                AGENT_CARD.version,
        }
    )


# =========================================================
# Application
# =========================================================


def build_app() -> Starlette:

    handler = (
        DefaultRequestHandler(
            agent_executor=(
                DemoRemoteAgentExecutor()
            ),

            task_store=(
                InMemoryTaskStore()
            ),

            agent_card=(
                AGENT_CARD
            ),
        )
    )

    routes = [
        Route(
            "/health",
            health,
            methods=[
                "GET"
            ],
        )
    ]

    # =====================================================
    # Agent Card
    #
    # GET:
    #
    # /.well-known/agent-card.json
    # =====================================================

    routes.extend(
        create_agent_card_routes(
            AGENT_CARD,
            card_url=(
                AGENT_CARD_WELL_KNOWN_PATH
            ),
        )
    )

    # =====================================================
    # A2A JSON-RPC
    #
    # POST /
    # =====================================================

    routes.extend(
        create_jsonrpc_routes(
            handler,
            rpc_url="/",
        )
    )

    return Starlette(
        routes=routes
    )


app = build_app()


if __name__ == "__main__":

    print(
        "\n"
        "========================================"
    )

    print(
        "AgentMesh Remote A2A Demo Agent"
    )

    print(
        "========================================"
    )

    print(
        f"Server:     {PUBLIC_URL}"
    )

    print(
        (
            "Agent Card: "
            f"{PUBLIC_URL}"
            f"{AGENT_CARD_WELL_KNOWN_PATH}"
        )
    )

    print(
        f"Health:     {PUBLIC_URL}/health"
    )

    print(
        "Protocol:   A2A / JSON-RPC"
    )

    print(
        "========================================"
        "\n"
    )

    uvicorn.run(
        app,
        host=HOST,
        port=PORT,
    )