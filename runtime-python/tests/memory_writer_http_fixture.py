"""Invoke the production Python writer against a real Go internal endpoint."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.memory.long_term import AutomaticLongTermMemoryWriter, ControlPlaneLongTermMemorySink, ModelBackedMemoryExtractor
from app.models.contracts import ModelResponse


class Gateway:
    async def generate(self, request):
        return ModelResponse(
            content=json.dumps({"items": [{"category": "goal", "memory_key": "goal.career.target_role",
                                           "content": "用户倾向 Agent 开发岗位", "confidence": .86}]}, ensure_ascii=False),
            provider="fixture", model=request.model, input_tokens=1, output_tokens=1,
            total_tokens=2, latency_ms=1, finish_reason="stop", estimated_cost=0,
        )


async def main():
    base_url, token, user_id = sys.argv[1], sys.argv[2], int(sys.argv[3])
    sink = ControlPlaneLongTermMemorySink(internal_token=token, base_url=base_url, timeout_seconds=5)
    rule = AutomaticLongTermMemoryWriter(sink=sink)
    inferred = AutomaticLongTermMemoryWriter(
        sink=sink, model_extractor=ModelBackedMemoryExtractor(Gateway(), model_name="fixture")
    )
    outcomes = [
        await rule.process(user_id=user_id, text="请记住：界面优先使用中文"),
        await rule.process(user_id=user_id, text="请记住：界面优先使用中文"),
        await inferred.process(user_id=user_id, text="我更倾向 Agent 开发岗位"),
    ]
    print(json.dumps([{"status": o.status, "extractor": o.extractor, **o.trace_detail()} for o in outcomes],
                     ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
