"""Generate QA data using the production Context Builder and Provenance code.

Import only their dependency-light source modules to keep this fixture runnable
without starting Redis/Milvus or importing the entire Runtime application.
No production source is rewritten. No user data is read or emitted.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import types

APP = Path(__file__).resolve().parents[3] / "runtime-python" / "app"


def package(name: str) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__path__ = []
    sys.modules[name] = module
    return module


def load(name: str, path: Path) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


package("app")
rag = package("app.rag")
rag_runtime = load("app.rag.runtime", APP / "rag" / "runtime.py")
provenance = load("app.rag.provenance", APP / "rag" / "provenance.py")
rag.EvidenceProvenance = provenance.EvidenceProvenance
rag.RetrievalHit = rag_runtime.RetrievalHit
rag.build_evidence_provenance = provenance.build_evidence_provenance
memory = package("app.memory")
memory.MemoryMessage = object
memory.RetrievedLongTermMemory = object
memory_context = types.ModuleType("app.memory.conversation_context")
memory_context.RetrievedConversationMemory = object
memory_context.render_retrieved_conversation_memories = lambda values: ""
sys.modules[memory_context.__name__] = memory_context
ctx = load("app.services.context_builder", APP / "services" / "context_builder.py")

kind = sys.argv[1] if len(sys.argv) > 1 else "GLOBAL"
if kind not in ("GLOBAL", "PROJECT"):
    raise SystemExit("invalid fixture kind")
marker = f"AGENTMESH_V41_{kind}_999888777666"
hits = [
    rag_runtime.RetrievalHit(
        document=rag_runtime.RetrievalDocument(
            id="qa-production-chunk-1",
            text="无关的测试资料。",
            source="other.txt",
            metadata={"documentType": "text", "chunkIndex": 0},
        ),
        score=0.92,
    ),
    rag_runtime.RetrievalHit(
        document=rag_runtime.RetrievalDocument(
            id="qa-production-chunk-2",
            text=f"测试标记是 {marker}。",
            source="knowledge.txt",
            metadata={"documentType": "text", "chunkIndex": 1},
        ),
        score=0.91,
    ),
]
context = ctx.build_agent_context(
    task="请根据当前授权资料回答测试标记是什么？",
    memory_messages=[], retrieval_hits=hits, grounding_sufficient=True,
)
print(json.dumps({"context": context, "marker": marker, "citationId": 2}, ensure_ascii=False))
