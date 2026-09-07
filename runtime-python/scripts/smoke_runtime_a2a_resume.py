from __future__ import annotations

import asyncio
import json

from app.schemas import (
    AgentProfile,
    RuntimeRequest,
)

from app.services import (
    create_registry,
)

from app.services.engine import (
    RuntimeEngine,
)


async def main() -> None:

    registry = (
        await create_registry()
    )

    engine = (
        RuntimeEngine(
            registry
        )
    )

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

    try:

        # =============================================
        # ROUND 1
        # =============================================

        print(
            "\n========== ROUND 1 =========="
        )

        first = (
            await engine.run(
                RuntimeRequest(
                    user_id=1,

                    request_id=(
                        "runtime-a2a-1"
                    ),

                    task=(
                        "帮我查询订单状态。"
                    ),

                    scheduler="fixed",

                    planner="heuristic",

                    execution_mode=(
                        "sequential"
                    ),

                    synthesis_mode=(
                        "never"
                    ),

                    agents=[
                        agent
                    ],
                )
            )
        )

        print(
            json.dumps(
                first.model_dump(
                    by_alias=True
                ),
                ensure_ascii=False,
                indent=2,
            )
        )

        assert (
            first.status
            == "INPUT_REQUIRED"
        )

        assert (
            first.continuation
            is not None
        )

        # 非失败！
        assert not any(
            item.success is False
            for item
            in first.agent_feedback
        )

        continuation = (
            first.continuation
        )

        # =============================================
        # ROUND 2
        # =============================================

        print(
            "\n========== ROUND 2 / RESUME =========="
        )

        second = (
            await engine.run(
                RuntimeRequest(
                    user_id=1,

                    request_id=(
                        "runtime-a2a-2"
                    ),

                    task=(
                        "订单号是 "
                        "ORDER202609030001"
                    ),

                    scheduler="fixed",

                    planner="heuristic",

                    execution_mode=(
                        "sequential"
                    ),

                    synthesis_mode=(
                        "never"
                    ),

                    agents=[
                        agent
                    ],

                    continuation=(
                        continuation
                    ),
                )
            )
        )

        print(
            json.dumps(
                second.model_dump(
                    by_alias=True
                ),
                ensure_ascii=False,
                indent=2,
            )
        )

        assert (
            second.status
            == "COMPLETED"
        )

        assert (
            second.continuation
            is None
        )

        assert (
            "ORDER202609030001"
            in second.answer
        )

        print(
            "\n"
            "======================================"
        )

        print(
            "AgentMesh Runtime Suspend/Resume PASS"
        )

        print(
            "======================================"
        )

    finally:

        await engine.close()


if __name__ == "__main__":

    asyncio.run(
        main()
    )