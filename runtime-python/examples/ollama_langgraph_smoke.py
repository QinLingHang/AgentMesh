import asyncio

from app.schemas import (
    AgentProfile,
    RuntimeRequest,
)
from app.services import (
    RuntimeEngine,
    create_registry,
)


def create_langgraph_agent() -> AgentProfile:
    return AgentProfile(
        id=9001,
        name="LocalQwenLangGraphAgent",
        description=(
            "LangGraph agent powered by "
            "local Ollama Qwen3"
        ),
        endpoint="langgraph://local-qwen",
        protocol="langgraph",
        capabilities=[
            "general",
        ],
        provider="ollama",
        modelName="qwen3:8b",
        qualityScore=0.9,
        successRate=1.0,
        failureRate=0.0,
        currentLoad=0.0,
        status="healthy",
    )


async def main() -> None:
    registry = await create_registry()

    try:
        engine = RuntimeEngine(
            registry
        )

        request = RuntimeRequest(
            user_id=1,
            request_id=(
                "ollama-langgraph-smoke"
            ),
            task=(
                "请用两句话解释 AI Agent，"
                "并说明它和普通聊天机器人"
                "最核心的区别。"
            ),
            scheduler="greedy",
            agents=[
                create_langgraph_agent()
            ],
        )

        print(
            "=== AgentMesh "
            "LangGraph + Ollama Smoke ==="
        )

        result = await engine.run(
            request
        )

        print()
        print("=== Answer ===")
        print(result.answer)

        print()
        print("=== Selected Agents ===")
        print(result.selected_agents)

        print()
        print("=== Execution Trace ===")

        for item in result.trace:
            print(
                f"[{item.kind}] "
                f"{item.title} "
                f"status={item.status}"
            )

            if item.detail:
                print(
                    f"  detail={item.detail}"
                )

        print()
        print("=== Feedback ===")

        for item in result.agent_feedback:
            print(item)

    finally:
        await registry.stop_all()


if __name__ == "__main__":
    asyncio.run(main())