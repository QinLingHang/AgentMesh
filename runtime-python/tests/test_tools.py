import asyncio
from types import SimpleNamespace
import pytest
from app.models import ModelGateway, ModelMessage, ModelRequest, ModelResponse, ModelTool, ToolCall
from app.models.errors import ModelError, ModelErrorType
from app.models.providers import MockModelProvider, OpenAICompatibleModelProvider
from app.tools import ToolApprovalRequired, ToolDefinition, ToolError, ToolErrorType, ToolLoopRunner, ToolRegistry, register_demo_tools
from app.schemas import AgentProfile, RuntimeRequest
from app.services import RuntimeEngine, create_registry

def run(coro): return asyncio.run(coro)

def test_registry_and_internal_execution():
    registry=ToolRegistry();register_demo_tools(registry)
    assert registry.get("get_order").name=="get_order" and len(registry.list())==3
    assert run(registry.execute("get_order",{"query":"x"}))["orderId"]=="ORD-1001"

def test_not_found_invalid_and_requires_approval():
    registry=ToolRegistry()
    with pytest.raises(ToolError) as missing: registry.get("missing")
    assert missing.value.error_type==ToolErrorType.NOT_FOUND
    registry.register(ToolDefinition(name="blocked",requires_confirmation=True),lambda a:a)
    with pytest.raises(ToolError) as blocked: run(registry.execute("blocked",{}))
    assert blocked.value.error_type==ToolErrorType.REQUIRES_APPROVAL
    with pytest.raises(ToolError) as invalid: run(registry.execute("blocked",[]))
    assert invalid.value.error_type in {ToolErrorType.REQUIRES_APPROVAL,ToolErrorType.INVALID_ARGUMENTS}

def test_timeout_and_execution_error_normalization():
    async def slow(_): await asyncio.sleep(.1)
    registry=ToolRegistry(timeout=.001);registry.register(ToolDefinition(name="slow"),slow)
    with pytest.raises(ToolError) as raised: run(registry.execute("slow",{}))
    assert raised.value.error_type==ToolErrorType.TIMEOUT
    registry=ToolRegistry();registry.register(ToolDefinition(name="boom"),lambda _:(_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(ToolError) as raised: run(registry.execute("boom",{}))
    assert raised.value.error_type==ToolErrorType.EXECUTION_FAILED

def test_mock_tool_call_observation_and_loop_trace():
    provider=MockModelProvider(); gateway=ModelGateway(provider,timeout=1,max_retries=0)
    req=ModelRequest(model="mock",messages=[ModelMessage(role="user",content="get order")],tools=[ModelTool(name="get_order")])
    first=run(provider.generate(req)); assert first.tool_calls[0].name=="get_order"
    req.messages.append(ModelMessage(role="tool",content='{"status":"PAID"}',tool_call_id=first.tool_calls[0].id))
    assert "Tool observation" in run(provider.generate(req)).content
    registry=ToolRegistry();register_demo_tools(registry);events=[]
    answer=run(ToolLoopRunner(gateway,"mock",registry).run("get order",on_tool_event=events.append))
    assert answer and [e["title"] for e in events]==["Tool Selected","Tool Started","Tool Completed"]

def test_max_iterations_is_bounded():
    class Infinite:
        name="infinite"
        async def generate(self,req): return ModelResponse(content="",provider="infinite",model=req.model,tool_calls=[ToolCall(id="1",name="get_order",arguments={})])
    registry=ToolRegistry();register_demo_tools(registry)
    with pytest.raises(ToolError) as raised: run(ToolLoopRunner(ModelGateway(Infinite(),timeout=1,max_retries=0),"m",registry,max_iterations=2).run("order"))
    assert "MAX_TOOL_ITERATIONS" in str(raised.value)

def test_openai_compatible_mapping_and_invalid_json():
    def response(arguments):
        call=SimpleNamespace(id="c1",function=SimpleNamespace(name="get_order",arguments=arguments))
        msg=SimpleNamespace(content=None,tool_calls=[call]); choice=SimpleNamespace(message=msg,finish_reason="tool_calls")
        return SimpleNamespace(usage=None,choices=[choice],model="fake")
    class Create:
        def __init__(self,value):self.value=value;self.kwargs=None
        async def create(self,**kwargs):self.kwargs=kwargs;return self.value
    provider=OpenAICompatibleModelProvider.__new__(OpenAICompatibleModelProvider);create=Create(response('{"id":1}'));provider.client=SimpleNamespace(chat=SimpleNamespace(completions=create))
    req=ModelRequest(model="fake",messages=[ModelMessage(role="user",content="order")],tools=[ModelTool(name="get_order",input_schema={"type":"object"})])
    mapped = run(provider.generate(req))
    assert mapped.tool_calls[0].arguments=={"id":1} and create.kwargs["tools"][0]["type"]=="function"
    # __new__ fixtures intentionally bypass __init__; provider parsing must
    # still treat absent pricing metadata as unknown instead of crashing.
    assert mapped.estimated_cost is None
    provider.client.chat.completions=Create(response("not-json"))
    with pytest.raises(ModelError) as raised: run(provider.generate(req))
    assert raised.value.error_type==ModelErrorType.BAD_REQUEST

def test_runtime_tool_trace_and_backward_compatible_no_tools():
    async def scenario():
        registry=await create_registry()
        try:
            agent=AgentProfile(id=1,name="General",endpoint="internal://general",protocol="internal",capabilities=["general"])
            engine=RuntimeEngine(registry)
            plain=await engine.run(RuntimeRequest(user_id=1,request_id="plain",task="hello",agents=[agent]))
            assert plain.answer
            result=await engine.run(RuntimeRequest(user_id=1,request_id="tool",task="get order",agents=[agent],tools=[ToolDefinition(name="get_order")]))
            assert result.answer and {x.title for x in result.trace if x.kind=="tool"} >= {"Tool Selected","Tool Started","Tool Completed"}
        finally: await registry.stop_all()
    run(scenario())

def test_tool_contract_accepts_camel_case_go_json():
    tool = ToolDefinition.model_validate(
        {
            "id": 99,

            "name":
                "delete_order",

            "description":
                "dangerous operation",

            "protocol":
                "internal",

            "inputSchema": {
                "type":
                    "object",
            },

            "riskLevel":
                "high",

            "requiresConfirmation":
                True,

            "enabled":
                True,
        }
    )

    assert (
        tool.risk_level
        == "high"
    )

    assert (
        tool.requires_confirmation
        is True
    )

    assert (
        tool.input_schema[
            "type"
        ]
        == "object"
    )


def test_high_risk_tool_requires_approval_even_without_flag():
    registry = (
        ToolRegistry()
    )

    executed = []

    registry.register(
        ToolDefinition(
            name="dangerous",
            riskLevel="high",
            requiresConfirmation=False,
        ),

        lambda arguments:
            executed.append(
                arguments
            ),
    )

    with pytest.raises(
        ToolError
    ) as raised:
        run(
            registry.execute(
                "dangerous",
                {},
            )
        )

    assert (
        raised.value
        .error_type
        == (
            ToolErrorType
            .REQUIRES_APPROVAL
        )
    )

    assert executed == []


def test_explicit_human_approval_allows_high_risk_tool():
    registry = (
        ToolRegistry()
    )

    registry.register(
        ToolDefinition(
            name="dangerous",
            riskLevel="high",
        ),

        lambda arguments: {
            "executed": True,
            "arguments":
                arguments,
        },
    )

    result = run(
        registry.execute(
            "dangerous",

            {
                "id": 1
            },

            approved_tools={
                "dangerous"
            },
        )
    )

    assert (
        result["executed"]
        is True
    )


def test_disabled_tool_cannot_be_bypassed_by_approval():
    registry = (
        ToolRegistry()
    )

    registry.register(
        ToolDefinition(
            name="disabled_tool",
            enabled=False,
            riskLevel="high",
        ),

        lambda arguments: {
            "should":
                "never happen"
        },
    )

    with pytest.raises(
        ToolError
    ) as raised:
        run(
            registry.execute(
                "disabled_tool",
                {},

                approved_tools={
                    "disabled_tool"
                },
            )
        )

    assert (
        raised.value
        .error_type
        == (
            ToolErrorType
            .PERMISSION_DENIED
        )
    )


def test_tool_loop_high_risk_emits_approval_without_execution():
    class HighRiskProvider:
        name = "high-risk"

        async def generate(
            self,
            request,
        ):
            return ModelResponse(
                content="",

                provider=(
                    self.name
                ),

                model=(
                    request.model
                ),

                tool_calls=[
                    ToolCall(
                        id="approval-call",

                        name=(
                            "dangerous"
                        ),

                        arguments={
                            "id": 1
                        },
                    )
                ],
            )

    executed = []

    registry = (
        ToolRegistry()
    )

    registry.register(
        ToolDefinition(
            name="dangerous",

            description=(
                "dangerous action"
            ),

            riskLevel="high",
        ),

        lambda arguments:
            executed.append(
                arguments
            ),
    )

    events = []

    with pytest.raises(ToolApprovalRequired) as raised:
        run(
            ToolLoopRunner(
                ModelGateway(
                    HighRiskProvider(),

                    timeout=1,

                    max_retries=0,
                ),

                "test",

                registry,
            ).run(
                "execute dangerous action",

                on_tool_event=(
                    events.append
                ),
            )
        )

    titles = [
        event["title"]
        for event
        in events
    ]

    assert titles == [
        "Tool Selected",
        "Tool Approval Required",
    ]

    approval = raised.value.request
    assert approval.tool_name == "dangerous"
    assert approval.risk_level == "high"
    assert approval.arguments == {"id": 1}
    assert approval.fingerprint
    assert executed == []


def test_openai_compatible_pricing_formula_when_configured():
    usage = SimpleNamespace(prompt_tokens=1_000_000, completion_tokens=500_000, total_tokens=1_500_000)
    msg = SimpleNamespace(content="ok", tool_calls=[])
    choice = SimpleNamespace(message=msg, finish_reason="stop")
    response = SimpleNamespace(usage=usage, choices=[choice], model="priced")

    class Create:
        async def create(self, **kwargs):
            return response

    provider = OpenAICompatibleModelProvider.__new__(OpenAICompatibleModelProvider)
    provider.client = SimpleNamespace(chat=SimpleNamespace(completions=Create()))
    provider.input_cost_per_million = 2.0
    provider.output_cost_per_million = 4.0
    req = ModelRequest(model="priced", messages=[ModelMessage(role="user", content="hello")])
    result = run(provider.generate(req))
    assert result.estimated_cost == pytest.approx(4.0)
    assert result.total_tokens == 1_500_000


def test_openai_desktop_delete_tool_call_enters_governance_and_suspends_before_execution():
    """Exact Case 82 contract: Go-shaped metadata + OpenAI tool_call -> approval.

    This intentionally crosses the provider mapping and ToolLoop governance
    boundary in one test so a fixture/tool-call parsing regression cannot be
    mistaken for an Approval UI or Desktop Bridge failure.
    """

    executed: list[dict] = []

    tool = ToolDefinition.model_validate(
        {
            "id": 82,
            "name": "local.fs.delete",
            "description": "Delete an authorized local file.",
            "protocol": "internal",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "recursive": {"type": "boolean"},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
            "riskLevel": "high",
            "requiresConfirmation": True,
            "enabled": True,
        }
    )

    call = SimpleNamespace(
        id="call_case82_delete",
        function=SimpleNamespace(
            name="local.fs.delete",
            arguments='{"path":"C:/AgentMesh/case82.txt","recursive":false}',
        ),
    )
    message = SimpleNamespace(content=None, tool_calls=[call])
    choice = SimpleNamespace(message=message, finish_reason="tool_calls")
    response = SimpleNamespace(usage=None, choices=[choice], model="case82-fixture")

    class Create:
        async def create(self, **kwargs):
            names = [item["function"]["name"] for item in kwargs.get("tools", [])]
            assert names == ["local.fs.delete"]
            return response

    provider = OpenAICompatibleModelProvider.__new__(OpenAICompatibleModelProvider)
    provider.client = SimpleNamespace(chat=SimpleNamespace(completions=Create()))

    registry = ToolRegistry()
    registry.register(tool, lambda arguments: executed.append(arguments))

    events = []
    with pytest.raises(ToolApprovalRequired) as raised:
        run(
            ToolLoopRunner(
                ModelGateway(provider, timeout=1, max_retries=0),
                "case82-fixture",
                registry,
            ).run(
                "delete the authorized test file",
                on_tool_event=events.append,
            )
        )

    approval = raised.value.request
    assert approval.tool_name == "local.fs.delete"
    assert approval.risk_level == "high"
    assert approval.requires_confirmation is True
    assert approval.arguments == {
        "path": "C:/AgentMesh/case82.txt",
        "recursive": False,
    }
    assert [event["title"] for event in events] == [
        "Tool Selected",
        "Tool Approval Required",
    ]
    assert executed == []
