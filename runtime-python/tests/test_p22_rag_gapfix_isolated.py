"""Isolated tests for P22 native ToolLoop streaming and RAG step gating.

The production modules are loaded directly, avoiding optional a2a/mcp/openai
packages that are unavailable in the offline verification container.
"""
from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from app.models.contracts import ModelResponse, ToolCall
from app.models.gateway import ModelGateway
from app.tools.contracts import ToolDefinition
from app.tools.loop import ToolLoopRunner
from app.tools.registry import ToolRegistry

ROOT = Path(__file__).resolve().parents[1] / "app" / "services"


def load_production_module(name: str):
    # app.services/__init__.py imports the entire Runtime (optional a2a/mcp);
    # directly load the unmodified source under a unique testing name.
    file = ROOT / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"isolated_gapfix_{name}", file)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod.__name__] = mod
    if name in {"knowledge_step_gate", "dag_executor"}:
        # The annotation is postponed and implementation needs only a plan's
        # .steps contract. Avoid importing app.planning/__init__.py here.
        import ast
        tree = ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
        skipped_import = (
            "app.planning.contracts" if name == "knowledge_step_gate" else "app.schemas"
        )
        tree.body = [node for node in tree.body if not (
            isinstance(node, ast.ImportFrom) and node.module == skipped_import
        )]
        if name == "dag_executor":
            mod.__dict__.update(DAGNode=object, DynamicDAG=object)
        exec(compile(tree, str(file), "exec"), mod.__dict__)
    else:
        spec.loader.exec_module(mod)
    return mod


def step(identifier, dependency="NONE", parents=()):
    return SimpleNamespace(id=identifier, objective=identifier, knowledge_dependency=dependency,
                           depends_on=list(parents))


def test_missing_required_blocks_transitive_dependents_but_not_siblings():
    policy = load_production_module("knowledge_step_gate")
    plan = SimpleNamespace(steps=[
        step("read_order"), step("policy", "REQUIRED"),
        step("refund", parents=("policy",)),
        step("notify", parents=("refund",)), step("unrelated"),
    ])
    result = policy.partition_knowledge_steps(plan, insufficient_required={"policy"})
    assert result.blocked == {
        "policy": "required_evidence_unavailable",
        "refund": "upstream_required_evidence_unavailable",
        "notify": "upstream_required_evidence_unavailable",
    }
    assert result.runnable == ("read_order", "unrelated") and result.partial


def test_unmapped_global_requirement_fail_closed_and_unknown_step_rejected():
    policy = load_production_module("knowledge_step_gate")
    plan = SimpleNamespace(steps=[step("first"), step("second")])
    result = policy.partition_knowledge_steps(
        plan, insufficient_required=set(), global_requirement_unresolved=True,
    )
    assert set(result.blocked) == {"first", "second"}
    assert not result.runnable
    with pytest.raises(ValueError, match="unknown REQUIRED"):
        policy.partition_knowledge_steps(plan, insufficient_required={"ghost"})
    with pytest.raises(ValueError, match="only directly block REQUIRED"):
        policy.partition_knowledge_steps(plan, insufficient_required={"first"})


def test_dag_executor_does_not_run_blocked_node_or_downstream():
    executor = load_production_module("dag_executor")
    def node(identifier, kind="agent", status="pending"):
        return SimpleNamespace(id=identifier, kind=kind, status=status, label=identifier,
                               agent_name=None, capability="general", optional=False,
                               condition=None)
    def edge(source, target):
        return SimpleNamespace(source=source, target=target)
    dag = SimpleNamespace(nodes=[
        node("task", "task", "completed"), node("step-query"), node("step-policy"),
        node("step-refund"), node("synthesize", "synthesis"),
    ], edges=[
        edge("task", "step-query"), edge("task", "step-policy"),
        edge("step-policy", "step-refund"), edge("step-query", "synthesize"),
        edge("step-refund", "synthesize"),
    ])
    executed, events = [], []
    async def run_node(node, upstream):
        executed.append(node.id)
        return ("test", "safe result", [], 0.0)
    result = asyncio.run(executor.DAGExecutor().execute(
        dag, run_node, events.append, blocked_node_reasons={
            "step-policy": "required_evidence_unavailable",
        },
    ))
    assert executed == ["step-query"]
    assert set(result.skipped_nodes) == {"step-policy", "step-refund"}
    assert "step-policy" not in result.outputs and "step-refund" not in result.outputs
    assert len([e for e in events if e["title"] == "DAG Node Blocked: Missing Knowledge"]) == 2


def test_dag_unknown_blocked_node_fails_closed_before_execution():
    executor = load_production_module("dag_executor")
    node = SimpleNamespace(id="step-safe", kind="agent", status="pending")
    dag = SimpleNamespace(nodes=[node], edges=[])
    executed = []
    async def run_node(*args):
        executed.append(args)
    with pytest.raises(executor.DAGExecutionError, match="invalid blocked"):
        asyncio.run(executor.DAGExecutor().execute(
            dag, run_node, blocked_node_reasons={"missing": "no_evidence"},
        ))
    assert not executed


def test_dag_previously_completed_blocked_step_fails_closed():
    executor = load_production_module("dag_executor")
    node = SimpleNamespace(id="step-policy", kind="agent", status="completed")
    dag = SimpleNamespace(nodes=[node], edges=[])
    with pytest.raises(executor.DAGExecutionError, match="previously completed"):
        asyncio.run(executor.DAGExecutor().execute(
            dag, lambda *args: None,
            blocked_node_reasons={"step-policy": "required_evidence_unavailable"},
        ))


class NativeToolProvider:
    name = "openai_compatible"
    def __init__(self):
        self.calls = 0
        self.stream_calls = 0
    async def generate(self, request):
        self.calls += 1
        if not any(m.role == "tool" for m in request.messages):
            assert len(request.tools) == 1
            return ModelResponse(
                content="", model=request.model, provider=self.name,
                tool_calls=[ToolCall(id="t1", name="calculate", arguments={"n": 4})],
            )
        assert len(request.tools) == 1
        return ModelResponse(content="draft not shown", model=request.model, provider=self.name)
    async def stream(self, request):
        self.stream_calls += 1
        assert request.tools == []
        assert sum(m.role == "tool" for m in request.messages) == 1
        yield {"type": "delta", "delta": "final "}
        yield {"type": "delta", "delta": "answer"}
        yield {"type": "done", "content": "final answer", "model": request.model,
               "provider": self.name}


def test_tool_loop_streams_only_final_answer_and_never_replays_tool():
    provider = NativeToolProvider()
    gateway = ModelGateway(provider, timeout=10, max_retries=0)
    registry = ToolRegistry()
    tool_calls = []
    def calculate(args):
        tool_calls.append(args)
        return {"value": args["n"] * 2}
    registry.register(ToolDefinition(name="calculate", inputSchema={"type": "object"}), calculate)
    deltas = []
    answer = asyncio.run(ToolLoopRunner(gateway, "test-model", registry).run(
        "calculate", on_delta=deltas.append,
    ))
    assert answer == "final answer" and deltas == ["final ", "answer"]
    assert len(tool_calls) == 1 and tool_calls[0] == {"n": 4}
    assert provider.calls == 2 and provider.stream_calls == 1


def test_mock_tool_loop_never_fakes_delta():
    class MockProvider(NativeToolProvider):
        name = "mock"
    provider = MockProvider()
    gateway = ModelGateway(provider, timeout=10, max_retries=0)
    registry = ToolRegistry()
    calls = []
    registry.register(
        ToolDefinition(name="calculate", inputSchema={"type": "object"}),
        lambda args: calls.append(args) or {"value": args["n"] * 2},
    )
    deltas = []
    answer = asyncio.run(ToolLoopRunner(gateway, "mock", registry).run(
        "calculate", on_delta=deltas.append,
    ))
    assert answer == "draft not shown"
    assert not deltas and provider.stream_calls == 0
    assert len(calls) == 1


def test_native_tool_stream_interruption_does_not_rerun_side_effects():
    class BrokenStreamProvider(NativeToolProvider):
        async def stream(self, request):
            self.stream_calls += 1
            yield {"type": "delta", "delta": "visible"}
            raise ConnectionError("stream interrupted")
    provider = BrokenStreamProvider()
    gateway = ModelGateway(provider, timeout=10, max_retries=3)
    registry = ToolRegistry()
    calls = []
    registry.register(
        ToolDefinition(name="calculate", inputSchema={"type": "object"}),
        lambda args: calls.append(args) or {"value": 8},
    )
    deltas = []
    with pytest.raises(ConnectionError, match="interrupted"):
        asyncio.run(ToolLoopRunner(gateway, "model", registry).run(
            "calculate", on_delta=deltas.append,
        ))
    assert deltas == ["visible"] and len(calls) == 1
    assert provider.stream_calls == 1 and provider.calls == 2
