import asyncio

from app.models import (
    ModelMessage,
    ModelRequest,
    ModelTool,
)
from app.services import create_registry
from app.tools import (
    ToolLoopRunner,
    ToolRegistry,
    register_demo_tools,
)


def create_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()

    register_demo_tools(
        registry
    )

    return registry


async def test_direct_tool_call(
    model,
    tool_registry: ToolRegistry,
) -> None:
    print(
        "=== Stage A: "
        "Direct Qwen Tool Call ==="
    )

    model_events = []

    tools = [
        ModelTool(
            name=tool.name,
            description=tool.description,
            input_schema=tool.input_schema,
        )
        for tool in tool_registry.list()
        if tool.enabled
    ]

    response = await model.gateway.generate(
        ModelRequest(
            model=model.model,
            messages=[
                ModelMessage(
                    role="system",
                    content=(
                        "You are an AgentMesh "
                        "Runtime execution model. "
                        "Use the provided tools "
                        "when they are needed."
                    ),
                ),
                ModelMessage(
                    role="user",
                    content=(
                        "Check the logistics status "
                        "for order "
                        "ORDER20260901001. "
                        "Use the logistics tool "
                        "instead of guessing."
                    ),
                ),
            ],
            tools=tools,
            temperature=0.2,
        ),
        model_events.append,
    )

    print()
    print("finish_reason:")
    print(response.finish_reason)

    print()
    print("content:")
    print(response.content)

    print()
    print("tool_calls:")

    if not response.tool_calls:
        print("NO TOOL CALL GENERATED")
    else:
        for call in response.tool_calls:
            print(
                {
                    "id": call.id,
                    "name": call.name,
                    "arguments": call.arguments,
                }
            )

    print()
    print("model_events:")

    for event in model_events:
        print(event)

    print()


async def test_full_tool_loop(
    model,
    tool_registry: ToolRegistry,
) -> None:
    print(
        "=== Stage B: "
        "Full Tool Loop ==="
    )

    model_events = []
    tool_events = []

    runner = ToolLoopRunner(
        model.gateway,
        model.model,
        tool_registry,
        max_iterations=5,
    )

    result = await runner.run(
        (
            "Check the logistics status "
            "for order ORDER20260901001. "
            "You must use the available "
            "logistics tool before answering."
        ),
        model_events.append,
        tool_events.append,
    )

    print()
    print("final_answer:")
    print(result)

    print()
    print("tool_events:")

    for event in tool_events:
        print(event)

    print()
    print("model_events:")

    for event in model_events:
        print(event)


async def main() -> None:
    registry = await create_registry()

    try:
        model = registry.context.get(
            "model.default"
        )

        print(
            "=== AgentMesh "
            "Ollama Tool Calling Smoke ==="
        )
        print(
            f"provider: {model.provider}"
        )
        print(
            f"model: {model.model}"
        )
        print()

        tool_registry = (
            create_tool_registry()
        )

        await test_direct_tool_call(
            model,
            tool_registry,
        )

        await test_full_tool_loop(
            model,
            tool_registry,
        )

    finally:
        await registry.stop_all()


if __name__ == "__main__":
    asyncio.run(main())