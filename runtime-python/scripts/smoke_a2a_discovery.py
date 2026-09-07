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
    # =====================================================
    # 1. Bootstrap AgentMesh Runtime
    # =====================================================

    registry = (
        await create_registry()
    )

    engine = (
        RuntimeEngine(
            registry
        )
    )

    try:
        # =================================================
        # 2. Create Remote A2A Agent
        #
        # 关键测试点：
        #
        # capabilities 故意为空。
        #
        # AgentMesh 必须通过 Agent Card 自动发现：
        #
        # general
        # document
        # =================================================

        remote_agent = (
            AgentProfile(
                id=9001,

                name=(
                    "RemoteA2ADiscoveryAgent"
                ),

                description=(
                    "Remote A2A agent "
                    "with automatically "
                    "discovered capabilities"
                ),

                endpoint=(
                    "http://127.0.0.1:9591"
                ),

                protocol="a2a",

                capabilities=[],
            )
        )

        # =================================================
        # 3. Runtime Request
        #
        # 这个任务应被 profiler 识别为 document。
        # =================================================

        request = (
            RuntimeRequest(
                user_id=1,

                request_id=(
                    "a2a-discovery-smoke"
                ),

                task=(
                    "Summarize this document."
                ),

                scheduler=(
                    "capability"
                ),

                planner=(
                    "heuristic"
                ),

                execution_mode=(
                    "sequential"
                ),

                synthesis_mode=(
                    "never"
                ),

                agents=[
                    remote_agent
                ],
            )
        )

        # =================================================
        # 4. Execute
        #
        # Expected:
        #
        # Task Profile
        #      ↓
        # A2A Agent Card Discovery
        #      ↓
        # skills
        #      ↓
        # AgentProfile capabilities
        #      ↓
        # Scheduler
        #      ↓
        # A2A execution
        # =================================================

        result = (
            await engine.run(
                request
            )
        )

        # =================================================
        # 5. Answer
        # =================================================

        print(
            "\n"
            "========== ANSWER =========="
        )

        print(
            result.answer
        )

        # =================================================
        # 6. Task Profile
        # =================================================

        print(
            "\n"
            "========== TASK PROFILE =========="
        )

        print(
            json.dumps(
                result
                .task_profile
                .model_dump(
                    by_alias=True
                ),
                ensure_ascii=False,
                indent=2,
            )
        )

        # =================================================
        # 7. Agent after Agent Card discovery
        # =================================================

        print(
            "\n"
            "========== AGENT AFTER DISCOVERY =========="
        )

        print(
            json.dumps(
                remote_agent
                .model_dump(
                    by_alias=True
                ),
                ensure_ascii=False,
                indent=2,
            )
        )

        # =================================================
        # 8. Selected Agent
        # =================================================

        print(
            "\n"
            "========== SELECTED =========="
        )

        print(
            json.dumps(
                result.selected_agents,
                ensure_ascii=False,
                indent=2,
            )
        )

        # =================================================
        # 9. Important Trace
        # =================================================

        print(
            "\n"
            "========== DISCOVERY / SCHEDULER / A2A TRACE =========="
        )

        for item in result.trace:
            if item.kind in {
                "profile",
                "a2a",
                "schedule",
                "agent",
            }:
                print(
                    json.dumps(
                        item.model_dump(
                            by_alias=True
                        ),
                        ensure_ascii=False,
                    )
                )

    finally:
        await engine.close()


if __name__ == "__main__":
    asyncio.run(
        main()
    )