"""Exercise the production Python retriever against the real Go/MySQL source."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.memory.retrieval import ControlPlaneLongTermMemorySource, HybridLongTermMemoryRetriever


async def main():
    base_url, token, user_id = sys.argv[1], sys.argv[2], int(sys.argv[3])
    source = ControlPlaneLongTermMemorySource(internal_token=token, base_url=base_url, timeout_seconds=5)
    retriever = HybridLongTermMemoryRetriever(source=source, embedding=None, top_k=4, min_score=.15)
    results = []
    for logical_context in ("normal", "project-a", "project-b"):
        outcome = await retriever.retrieve(user_id=user_id, query="Explain Go code")
        results.append({
            "logicalContext": logical_context,
            "status": outcome.status,
            "reason": outcome.reason,
            "ids": [item.memory.id for item in outcome.memories],
            "keys": [item.memory.memory_key for item in outcome.memories],
            "trace": outcome.trace_detail(),
        })
    print(json.dumps(results))


if __name__ == "__main__":
    asyncio.run(main())
