from __future__ import annotations

import asyncio
import json

from app.agents import (
    AgentExecutionRequest,
    AgentExecutorResolver,
)
from app.schemas import (
    AgentProfile,
)
from app.services import (
    create_registry,
)


async def main() -> None:

    # =====================================================
    # 1. AgentMesh Plugin Runtime
    # =====================================================

    registry = (
        await create_registry()
    )

    resolver = (
        AgentExecutorResolver(
            registry
        )
    )

    # =====================================================
    # 2. Remote heterogeneous A2A Agent
    #
    # AgentMesh 不知道它内部：
    #
    # - 用什么框架
    # - 用什么模型
    # - 有什么 Memory
    # - 有什么 Tools
    #
    # 只知道：
    #
    # protocol = a2a
    # endpoint = remote URL
    # =====================================================

    agent = (
        AgentProfile(
            id=9001,

            name=(
                "RemoteA2ADemoAgent"
            ),

            description=(
                "Independent remote "
                "A2A demo agent"
            ),

            endpoint=(
                "http://127.0.0.1:9591"
            ),

            protocol=(
                "a2a"
            ),

            capabilities=[
                "general"
            ],
        )
    )

    # =====================================================
    # 3. Resolver
    #
    # a2a
    #   ↓
    # agent.a2a
    #   ↓
    # A2AAgentPlugin
    # =====================================================

    executor = (
        resolver.resolve(
            agent.protocol
        )
    )

    runtime_events: list[
        dict
    ] = []

    # =====================================================
    # 4. Real A2A Execution
    # =====================================================

    result = (
        await executor.execute(
            AgentExecutionRequest(
                agent=(
                    agent
                ),

                capability=(
                    "general"
                ),

                task=(
                    "请说明你是否已经通过 "
                    "AgentMesh 的标准 A2A "
                    "协议收到这个远程任务。"
                ),

                on_runtime_event=(
                    runtime_events
                    .append
                ),
            )
        )
    )

    # =====================================================
    # 5. Output
    # =====================================================

    print(
        "\n"
        "========== RESULT =========="
    )

    print(
        result.content
    )

    print(
        "\n"
        "========== METADATA =========="
    )

    print(
        json.dumps(
            result.metadata,
            ensure_ascii=False,
            indent=2,
        )
    )

    print(
        "\n"
        "========== A2A TRACE =========="
    )

    for item in (
        runtime_events
    ):
        print(
            json.dumps(
                item,
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":

    asyncio.run(
        main()
    )