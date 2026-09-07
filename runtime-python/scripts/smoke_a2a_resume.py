from __future__ import annotations

import asyncio
import json

from app.agents import (
    A2AAgentExecutor,
    A2AAgentInterruptedError,
    AgentExecutionRequest,
)

from app.schemas import (
    AgentProfile,
)


async def main() -> None:

    agent = (
        AgentProfile(
            id=9002,

            name=(
                "RemoteA2AOrderAgent"
            ),

            endpoint=(
                "http://127.0.0.1:9591"
            ),

            protocol="a2a",

            capabilities=[
                "general"
            ],
        )
    )

    executor = (
        A2AAgentExecutor(
            timeout_seconds=15.0,
            trust_env=False,

            # =========================================
            # 这一次故意开 Streaming
            # =========================================

            streaming=True,
        )
    )

    trace: list[
        dict
    ] = []

    # =================================================
    # Round 1
    # =================================================

    first_request = (
        AgentExecutionRequest(
            agent=(
                agent
            ),

            capability=(
                "general"
            ),

            task=(
                "帮我查询订单状态。"
            ),

            on_runtime_event=(
                trace.append
            ),
        )
    )

    print(
        "\n"
        "========== ROUND 1 =========="
    )

    try:

        await executor.execute(
            first_request
        )

        raise RuntimeError(
            (
                "expected "
                "INPUT_REQUIRED"
            )
        )

    except (
        A2AAgentInterruptedError
    ) as interrupted:

        print(
            "Task interrupted correctly."
        )

        print(
            json.dumps(
                interrupted.metadata(),
                ensure_ascii=False,
                indent=2,
            )
        )

        task_id = (
            interrupted.task_id
        )

        context_id = (
            interrupted.context_id
        )

        assert (
            interrupted.task_state
            == (
                "TASK_STATE_"
                "INPUT_REQUIRED"
            )
        )

        assert task_id
        assert context_id

    # =================================================
    # Round 2
    #
    # Same:
    #     task_id
    #     context_id
    # =================================================

    print(
        "\n"
        "========== ROUND 2 / RESUME =========="
    )

    second_request = (
        AgentExecutionRequest(
            agent=(
                agent
            ),

            capability=(
                "general"
            ),

            task=(
                "订单号是 "
                "ORDER202609030001"
            ),

            on_runtime_event=(
                trace.append
            ),
        )
    )

    result = (
        await executor.resume(
            second_request,

            task_id=(
                task_id
            ),

            context_id=(
                context_id
            ),
        )
    )

    print(
        result.content
    )

    print(
        "\n"
        "========== RESULT METADATA =========="
    )

    print(
        json.dumps(
            result.metadata,
            ensure_ascii=False,
            indent=2,
        )
    )

    # =================================================
    # Validate same workflow
    # =================================================

    assert (
        result.metadata[
            "task_id"
        ]
        == task_id
    )

    assert (
        result.metadata[
            "context_id"
        ]
        == context_id
    )

    assert (
        result.metadata[
            "task_state"
        ]
        == (
            "TASK_STATE_COMPLETED"
        )
    )

    # =================================================
    # Trace
    # =================================================

    print(
        "\n"
        "========== A2A TRACE =========="
    )

    for item in trace:

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