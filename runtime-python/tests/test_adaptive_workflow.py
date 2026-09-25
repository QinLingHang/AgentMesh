import json

import pytest

from app.agents import (
    AgentExecutionRequest,
    AgentExecutionResult,
    AgentExecutorResolver,
)
from app.kernel import (
    AgentMeshPlugin,
    PluginKind,
    PluginManifest,
    PluginRegistry,
    RuntimeContext,
)
from app.planning import (
    ExecutionPlan,
    PlanStep,
    PlanValidationError,
    PlanValidator,
    SemanticTaskPlanner,
)
from app.schemas import AgentProfile, Assignment, TaskProfile
from app.services.dag_executor import DAGExecutor
from app.services.plan_compiler import PlanCompiler


@pytest.fixture()
def validator() -> PlanValidator:
    return PlanValidator(max_steps=8)


def _profile(*, capabilities, complexity="high", parallelizable=True):
    return TaskProfile(
        required_capabilities=list(capabilities),
        complexity=complexity,
        risk_level="low",
        modality=["text"],
        parallelizable=parallelizable,
    )


def test_simple_chinese_query_stays_on_fast_path(validator):
    planner = SemanticTaskPlanner(validator=validator)
    profile = _profile(capabilities=["general"], complexity="low", parallelizable=False)

    assert planner.should_plan(task="解释一下 Redis 是什么", profile=profile) is False


def test_complex_chinese_query_enters_semantic_planner(validator):
    planner = SemanticTaskPlanner(validator=validator)
    task = "分析系统架构和安全风险，并根据两部分分析结果给出最终优化方案。"
    profile = _profile(
        capabilities=["architecture_analysis", "security_analysis"],
        complexity="high",
        parallelizable=True,
    )

    assert planner.should_plan(task=task, profile=profile) is True
    assert len(planner._split_clauses(task)) >= 2


@pytest.mark.asyncio
async def test_complex_chinese_query_can_produce_fan_in_semantic_plan(validator):
    planner = SemanticTaskPlanner(validator=validator)
    task = "分析系统架构和安全风险，并根据两部分分析结果给出最终优化方案。"
    profile = _profile(
        capabilities=["architecture_analysis", "security_analysis"],
        complexity="high",
        parallelizable=True,
    )
    agents = [
        AgentProfile(
            id=1,
            name="ArchitectureAgent",
            endpoint="internal://architecture",
            protocol="internal",
            capabilities=["architecture_analysis"],
        ),
        AgentProfile(
            id=2,
            name="SecurityAgent",
            endpoint="internal://security",
            protocol="internal",
            capabilities=["security_analysis"],
        ),
        AgentProfile(
            id=3,
            name="SolutionAgent",
            endpoint="internal://solution",
            protocol="internal",
            capabilities=["solution_design"],
        ),
    ]

    class FakePlannerModel:
        async def generate(self, prompt, on_model_event=None):
            assert "AVAILABLE_CAPABILITIES" in prompt
            return json.dumps(
                {
                    "goal": task,
                    "requiresSynthesis": True,
                    "steps": [
                        {
                            "id": "architecture",
                            "objective": "分析当前系统架构",
                            "capability": "architecture_analysis",
                            "dependsOn": [],
                        },
                        {
                            "id": "security",
                            "objective": "分析当前系统安全风险",
                            "capability": "security_analysis",
                            "dependsOn": [],
                        },
                        {
                            "id": "solution",
                            "objective": "综合架构和安全分析形成优化方案",
                            "capability": "solution_design",
                            "dependsOn": ["architecture", "security"],
                        },
                    ],
                },
                ensure_ascii=False,
            )

    outcome = await planner.plan(
        task=task,
        profile=profile,
        agents=agents,
        model=FakePlannerModel(),
    )

    assert outcome.used_model is True
    assert [step.id for step in outcome.plan.steps] == [
        "architecture",
        "security",
        "solution",
    ]
    solution = outcome.plan.steps[-1]
    assert solution.depends_on == ["architecture", "security"]
    assert PlanCompiler.infer_topology(outcome.plan) == "hybrid"
    assert PlanCompiler.max_parallelism(outcome.plan) == 2


def test_self_dependency_is_rejected_fail_closed(validator):
    plan = ExecutionPlan(
        goal="unsafe self dependency",
        steps=[
            PlanStep(
                id="analysis",
                objective="Analyze",
                capability="general",
                dependsOn=["analysis"],
            )
        ],
    )

    with pytest.raises(PlanValidationError, match="cannot depend on itself"):
        validator.validate(
            plan,
            available_capabilities={"general"},
            baseline_capabilities=["general"],
        )


def test_duplicate_step_id_is_rejected_as_ambiguous(validator):
    plan = ExecutionPlan(
        goal="duplicate ids",
        steps=[
            PlanStep(id="analysis", objective="A", capability="general"),
            PlanStep(id="analysis", objective="B", capability="general"),
        ],
    )

    with pytest.raises(PlanValidationError, match="duplicate step id"):
        validator.validate(
            plan,
            available_capabilities={"general"},
            baseline_capabilities=["general"],
        )


class _FakeAgentPlugin(AgentMeshPlugin):
    def __init__(self, protocol: str, calls: dict[str, int], seen: dict[str, dict]):
        self.protocol = protocol
        self.calls = calls
        self.seen = seen
        self.manifest = PluginManifest(
            f"agent.{protocol}",
            f"Fake {protocol} Agent",
            "1.0.0",
            PluginKind.AGENT,
        )

    async def setup(self, context: RuntimeContext) -> None:
        self.context = context

    async def execute(self, request: AgentExecutionRequest) -> AgentExecutionResult:
        self.calls[self.protocol] = self.calls.get(self.protocol, 0) + 1
        self.seen[self.protocol] = {
            "agent_id": request.agent.id,
            "capability": request.capability,
            "task": request.task,
        }
        return AgentExecutionResult(
            content=f"{self.protocol}:{request.capability}",
            metadata={"protocol": self.protocol},
        )


@pytest.mark.asyncio
async def test_mixed_protocol_semantic_dag_routes_through_resolver_once_each():
    plan = ExecutionPlan(
        goal="mixed protocol semantic workflow",
        steps=[
            PlanStep(id="internal", objective="Internal analysis", capability="cap_internal"),
            PlanStep(id="langgraph", objective="Workflow analysis", capability="cap_langgraph"),
            PlanStep(
                id="http",
                objective="Remote HTTP synthesis",
                capability="cap_http",
                dependsOn=["internal", "langgraph"],
            ),
            PlanStep(
                id="a2a",
                objective="A2A finalization",
                capability="cap_a2a",
                dependsOn=["http"],
            ),
        ],
    )
    assignments = [
        Assignment(capability="cap_internal", agent_id=1, agent_name="Internal", stepId="internal"),
        Assignment(capability="cap_langgraph", agent_id=2, agent_name="LangGraph", stepId="langgraph"),
        Assignment(capability="cap_http", agent_id=3, agent_name="HTTP", stepId="http"),
        Assignment(capability="cap_a2a", agent_id=4, agent_name="A2A", stepId="a2a"),
    ]
    agents = {
        1: AgentProfile(
            id=1,
            name="Internal",
            endpoint="internal://mixed/internal",
            protocol="internal",
            capabilities=["cap_internal"],
        ),
        2: AgentProfile(
            id=2,
            name="LangGraph",
            endpoint="internal://mixed/langgraph",
            protocol="langgraph",
            capabilities=["cap_langgraph"],
        ),
        3: AgentProfile(
            id=3,
            name="HTTP",
            endpoint="https://example.invalid/agent",
            protocol="http",
            capabilities=["cap_http"],
        ),
        4: AgentProfile(
            id=4,
            name="A2A",
            endpoint="https://example.invalid/a2a",
            protocol="a2a",
            capabilities=["cap_a2a"],
        ),
    }

    calls: dict[str, int] = {}
    seen: dict[str, dict] = {}
    registry = PluginRegistry(RuntimeContext())
    for protocol in ("internal", "langgraph", "http", "a2a"):
        registry.register(_FakeAgentPlugin(protocol, calls, seen))
    resolver = AgentExecutorResolver(registry)

    dag = PlanCompiler().compile(plan, assignments)
    executor = DAGExecutor()

    async def execute_node(node, upstream):
        agent = agents[node.agent_id]
        plugin = resolver.resolve(agent.protocol)
        upstream_keys = ",".join(sorted(upstream))
        request = AgentExecutionRequest(
            agent=agent,
            capability=node.capability or "general",
            task=f"{node.objective}\nUPSTREAM={upstream_keys}",
        )
        result = await plugin.execute(request)
        return result.content

    result = await executor.execute(dag, execute_node)

    assert calls == {
        "internal": 1,
        "langgraph": 1,
        "http": 1,
        "a2a": 1,
    }
    assert result.outputs["step-internal"] == "internal:cap_internal"
    assert result.outputs["step-langgraph"] == "langgraph:cap_langgraph"
    assert result.outputs["step-http"] == "http:cap_http"
    assert result.outputs["step-a2a"] == "a2a:cap_a2a"

    # Both independent roots must finish before the HTTP fan-in node, and HTTP
    # must finish before the final A2A node.
    order = result.completion_order
    assert order.index("step-internal") < order.index("step-http")
    assert order.index("step-langgraph") < order.index("step-http")
    assert order.index("step-http") < order.index("step-a2a")

    # The dependency results are propagated into the downstream tasks.
    assert "step-internal" in seen["http"]["task"]
    assert "step-langgraph" in seen["http"]["task"]
    assert "step-http" in seen["a2a"]["task"]


def test_source_bounded_transform_step_cannot_invent_required_knowledge():
    from app.planning.contracts import ExecutionPlan, PlanStep
    from app.semantics.contracts import TaskSemanticIntent, KnowledgeDependency
    plan = ExecutionPlan(
        goal='summarize inline text',
        steps=[
            PlanStep(id='extract_points', objective='Extract three points from supplied text', capability='general'),
            PlanStep(id='format_output', objective='Generate the final summary from the extracted points', capability='general', dependsOn=['extract_points'], knowledgeDependency='REQUIRED'),
        ],
        requiresSynthesis=True,
    )
    semantic = TaskSemanticIntent(knowledgeDependency=KnowledgeDependency.NONE)
    reconciled = SemanticTaskPlanner._reconcile_source_bounded_knowledge(plan, semantic)
    assert reconciled.steps[1].knowledge_dependency == 'NONE'


def test_request_input_transform_root_cannot_invent_required_knowledge():
    from app.planning.contracts import ExecutionPlan, PlanStep
    from app.semantics.contracts import TaskSemanticIntent, KnowledgeDependency
    plan = ExecutionPlan(
        goal='summarize supplied text',
        steps=[
            PlanStep(
                id='summarize',
                objective='Summarize the material already supplied in the request',
                capability='general',
                knowledgeDependency='REQUIRED',
                inputSource='REQUEST_INPUT',
            ),
        ],
    )
    semantic = TaskSemanticIntent(knowledgeDependency=KnowledgeDependency.NONE)
    reconciled = SemanticTaskPlanner._reconcile_source_bounded_knowledge(plan, semantic)
    assert reconciled.steps[0].knowledge_dependency == 'NONE'


def test_inline_request_payload_downgrades_unlabeled_root_required_knowledge():
    from app.semantics import analyze_task_semantics

    task = (
        "请提炼下面文本的三个核心要点，然后生成一句不超过30字的摘要，最后以 JSON 输出。"
        "文本：Agent Runtime 负责承载智能体执行，并协调模型调用、工具调用、状态管理与任务流程。"
    )
    semantic = analyze_task_semantics(task)
    plan = ExecutionPlan(
        goal=task,
        steps=[
            PlanStep(
                id="extract", objective="提炼用户给出的文本", capability="general",
                inputSource="UNSPECIFIED", knowledgeDependency="REQUIRED",
            ),
            PlanStep(
                id="summary", objective="基于要点生成摘要", capability="general",
                dependsOn=["extract"], knowledgeDependency="REQUIRED",
            ),
        ],
    )
    reconciled = SemanticTaskPlanner._reconcile_source_bounded_knowledge(plan, semantic, task)
    assert [step.knowledge_dependency for step in reconciled.steps] == ["NONE", "NONE"]


def test_genuine_required_knowledge_step_is_not_downgraded():
    from app.planning.contracts import ExecutionPlan, PlanStep
    from app.semantics.contracts import TaskSemanticIntent, KnowledgeDependency
    plan = ExecutionPlan(
        goal='check company warranty policy',
        steps=[
            PlanStep(id='retrieve_policy', objective='Retrieve current company warranty policy', capability='general', knowledgeDependency='REQUIRED', inputSource='EXTERNAL'),
        ],
    )
    semantic = TaskSemanticIntent(knowledgeDependency=KnowledgeDependency.NONE)
    reconciled = SemanticTaskPlanner._reconcile_source_bounded_knowledge(plan, semantic)
    assert reconciled.steps[0].knowledge_dependency == 'REQUIRED'
