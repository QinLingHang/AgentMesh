import asyncio

from app.services import create_registry


async def main() -> None:
    registry = await create_registry()

    try:
        model = registry.context.get(
            "model.default"
        )

        print("=== AgentMesh Ollama Model Smoke ===")
        print(f"provider: {model.provider}")
        print(f"model: {model.model}")

        events = []

        response = await model.generate_response(
            "请用两句话解释什么是 AI Agent。",
            events.append,
        )

        print()
        print("=== Response ===")
        print(response.content)

        print()
        print("=== Metadata ===")
        print(f"provider: {response.provider}")
        print(f"model: {response.model}")
        print(
            f"input_tokens: "
            f"{response.input_tokens}"
        )
        print(
            f"output_tokens: "
            f"{response.output_tokens}"
        )
        print(
            f"total_tokens: "
            f"{response.total_tokens}"
        )
        print(
            f"latency_ms: "
            f"{response.latency_ms}"
        )
        print(
            f"finish_reason: "
            f"{response.finish_reason}"
        )

        print()
        print("=== Model Events ===")

        for event in events:
            print(event)

    finally:
        await registry.stop_all()


if __name__ == "__main__":
    asyncio.run(main())