import asyncio

import httpx
from openai import AsyncOpenAI


async def main() -> None:
    http_client = httpx.AsyncClient(
        trust_env=False,
    )

    client = AsyncOpenAI(
        api_key="ollama",
        base_url="http://127.0.0.1:11434/v1",
        http_client=http_client,
    )

    try:
        response = await client.chat.completions.create(
            model="qwen3:8b",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an AgentMesh Runtime "
                        "execution model."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "请用两句话解释什么是 AI Agent。"
                    ),
                },
            ],
            temperature=0.2,
        )

        print("=== SUCCESS ===")
        print(
            response.choices[0]
            .message.content
        )

        print()
        print("model:", response.model)
        print(
            "finish_reason:",
            response.choices[0].finish_reason,
        )
        print(
            "usage:",
            response.usage,
        )

    except Exception as exc:
        print("=== FAILED ===")
        print(
            "type:",
            type(exc).__name__,
        )
        print(
            "message:",
            str(exc),
        )

        response = getattr(
            exc,
            "response",
            None,
        )

        if response is not None:
            print(
                "status:",
                response.status_code,
            )

            try:
                print(
                    "body:",
                    response.text,
                )
            except Exception:
                pass

        raise

    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())