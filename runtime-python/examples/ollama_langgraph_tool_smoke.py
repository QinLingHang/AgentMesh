import asyncio

from app.schemas import (
    AgentProfile,
    RuntimeRequest,
)
from app.services import (
    RuntimeEngine,
    create_registry,
)
from app.tools.contracts import ToolDefinition


def create_agent() -> AgentProfile:
    return AgentProfile(
        id=9100,
        name="QwenLangGraphToolAgent",
        description=(
            "LangGraph agent powered by "
            "local Qwen3 with tool calling"
        ),
        endpoint="langgraph://qwen-tool",
        protocol="langgraph",
        capabilities=[
            "business",
        ],
        provider="ollama",
        modelName="qwen3:8b",
        qualityScore=0.90,
        avgLatencyMs=5000,
        avgCost=0.0,
        successRate=1.0,
        failureRate=0.0,
        currentLoad=0.0,
        status="ACTIVE",
    )


def create_logistics_tool() -> ToolDefinition:
    return ToolDefinition(
        id=9101,
        name="get_logistics",
        description=(
            "Get the logistics and shipping status "
            "for an order. Use this tool whenever "
            "the user asks about shipping, delivery "
            "or logistics information."
        ),
        protocol="internal",
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Order identifier or "
                        "logistics query"
                    ),
                },
            },
            "required": [
                "query",
            ],
            "additionalProperties": False,
        },
        risk_level="low",
        requires_confirmation=False,
        enabled=True,
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
                "ollama-langgraph-tool-smoke"
            ),
            task=(
                "Check the logistics status "
                "for order ORDER20260901001. "
                "You must use the available "
                "logistics tool before answering."
            ),
            scheduler="greedy",
            agents=[
                create_agent(),
            ],
            tools=[
                create_logistics_tool(),
            ],
        )

        print(
            "=== AgentMesh Full Runtime ==="
        )
        print(
            "LangGraph + Qwen3 + Tool Calling"
        )
        print()

        result = await engine.run(
            request
        )

        print("=== Answer ===")
        print(result.answer)

        print()
        print("=== Selected Agents ===")
        print(result.selected_agents)

        print()
        print("=== Task Profile ===")
        print(result.task_profile)

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
        print("=== Agent Feedback ===")

        for item in result.agent_feedback:
            print(item)

        print()
        print("=== Runtime Summary ===")
        print(
            f"elapsed_ms={result.elapsed_ms}"
        )
        print(
            f"estimated_cost="
            f"{result.estimated_cost}"
        )

    finally:
        await registry.stop_all()


if __name__ == "__main__":
    asyncio.run(main())