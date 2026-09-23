"""Binary P23 route contracts: no concrete capability choice at preflight.

These are curated unit examples, NOT the independently frozen real-stack QA set.
"""
import pytest
from pydantic import ValidationError
from app.semantics.intent_understanding import (
    TaskUnderstandingRequest, TaskUnderstandingResult, understand, needs_semantic_model,
)
from app.semantics.semantic_intent_model import SemanticIntentDescriptor


def route(text, **options):
    return understand(TaskUnderstandingRequest.model_validate({"task": text, **options}))


@pytest.mark.parametrize('text', [
    '你好', '您好', '谢谢', '再见', 'hello', 'hi', '早上好', '解释一下 Go slice',
    '什么是 Channel', '介绍一下 Python 切片', '什么是七天无理由退货？',
    'What is a warranty?', '解释一下 Go 协程',
])
def test_genuinely_model_only(text):
    value = route(text)
    assert value.execution_route == 'FAST_PATH'
    assert value.disposition == 'EXECUTE'
    assert value.model_calls == 0
    assert not value.capability_required


@pytest.mark.parametrize('text', [
    '你们的退货政策是什么？', '你们支持七天无理由退货吗？', '这个产品保修多久？',
    '会员有什么权益？', '请告诉我本店运费规则', '你们的退款政策',
    'What is your return policy?', '这个套餐怎么办理？', '这款商品可以退货吗？',
])
def test_customer_does_not_have_to_mention_knowledge_base(text):
    value = route(text)
    assert value.execution_route == 'RUNTIME'
    assert value.knowledge_dependency.value != 'NONE'
    assert value.capability_required


@pytest.mark.parametrize('text', [
    '我的订单现在到哪里了？', '查询订单状态', '我的物流到哪了',
    'my order status', '我的余额是多少', '运行一下测试', '列出项目文件',
    '检查代码并修复', '运行代码后生成报告', '给客户发邮件',
    '调用订单查询 API', '使用 MCP 获取结果', '委派外部 Agent',
])
def test_go_never_selects_an_individual_tool_or_agent(text):
    value = route(text)
    assert value.execution_route == 'RUNTIME'
    assert value.capability_required
    assert 'matchedCapabilityRefs' not in value.model_dump(by_alias=True)


def test_multi_step_is_runtime_not_an_extra_go_route():
    value = route('检查仓库，发现问题就修复，然后运行测试并报告')
    assert value.execution_route == 'RUNTIME'
    assert 'strategy' not in value.model_dump(by_alias=True)
    assert 'needsPlanner' not in value.model_dump(by_alias=True)


def test_no_capability_catalog_is_required_or_accepted():
    request = TaskUnderstandingRequest(task='我的订单状态')
    assert 'authorizedCapabilities' not in request.model_dump(by_alias=True)
    with pytest.raises(ValidationError):
        TaskUnderstandingRequest.model_validate({'task': '你好', 'authorizedCapabilities': [{'ref': 'TOOL:7'}]})


def test_explicit_rag_on_prevents_direct():
    assert route('你好', ragMode='ON').execution_route == 'RUNTIME'


def test_off_blocks_implicit_knowledge_without_invoking_capabilities():
    d = route('你们的保修政策是什么？', ragMode='OFF')
    assert d.execution_route == 'RUNTIME'
    assert d.disposition == 'CLARIFY'
    assert d.unresolved_requirements


def test_attachment_not_assumed_to_be_model_only():
    assert route('解释这个', hasAttachments=True).execution_route == 'RUNTIME'


@pytest.mark.parametrize('state', ['AMBIGUOUS', 'ONE_PENDING', 'NONE'])
def test_untrusted_continuation_never_resubmits(state):
    d = route('继续', continuationState=state)
    assert d.execution_route == 'RUNTIME'
    if state != 'CHAT':
        assert d.disposition == 'CLARIFY'


def test_chat_continuation_can_be_answered_inside_runtime_without_restarting_task():
    d = route('继续', continuationState='CHAT')
    assert d.execution_route == 'RUNTIME'  # conservative; no false FAST assumption


def test_missing_action_target_fails_closed():
    d = route('帮我处理这个')
    assert d.disposition == 'CLARIFY'
    assert d.execution_route == 'RUNTIME'


def test_model_descriptor_may_only_add_dependencies():
    req = TaskUnderstandingRequest(task='解释一下 Go slice')
    baseline = understand(req)
    injected = SemanticIntentDescriptor.model_validate({
        'objective': '解释一下 Go slice', 'capabilityKinds': ['TOOL'],
    })
    refined = understand(req, descriptor=injected)
    assert baseline.execution_route == 'FAST_PATH'
    assert refined.execution_route == 'RUNTIME'
    assert 'matchedCapabilityRefs' not in refined.model_dump(by_alias=True)


def test_descriptor_cannot_override_rag_off():
    req = TaskUnderstandingRequest(task='解释一下 Go slice', ragMode='OFF')
    descriptor = SemanticIntentDescriptor.model_validate({
        'objective': '解释一下 Go slice', 'knowledgeDependency': 'REQUIRED',
    })
    d = understand(req, descriptor=descriptor)
    assert d.disposition == 'CLARIFY'
    assert d.execution_route == 'RUNTIME'


def test_model_failure_fallback_cannot_downgrade_unknown():
    req = TaskUnderstandingRequest(task='这个怎么样？', allowModel=True)
    baseline = understand(req)
    assert baseline.execution_route == 'RUNTIME'
    assert baseline.model_calls == 0
    assert needs_semantic_model(req, baseline)
    assert not needs_semantic_model(req.model_copy(update={'allow_model': False}), baseline)


def test_schema_fail_closed_and_no_extra_model_fields():
    for payload in [
        {'schemaVersion': 'p23.v1', 'task': '你好'},
        {'task': '你好', 'projectId': 777},
        {'task': '你好', 'authorizedCapabilities': [{'ref': 'KNOWLEDGE:1'}]},
    ]:
        with pytest.raises(ValidationError):
            TaskUnderstandingRequest.model_validate(payload)
    with pytest.raises(ValidationError):
        TaskUnderstandingResult.model_validate({
            'executionRoute': 'SINGLE_CAPABILITY', 'knowledgeDependency': 'NONE',
        })


def test_model_credentials_not_serialized_in_response_or_dump():
    r = TaskUnderstandingRequest.model_validate({
        'task': '这个是什么？',
        'projectModel': {
            'provider': 'openai-compatible', 'baseUrl': 'http://localhost:1234',
            'modelName': 'model', 'apiKey': 'PRIVATE_SECRET',
        },
    })
    assert 'PRIVATE_SECRET' not in str(r.model_dump(by_alias=True))
    assert 'projectModel' not in r.model_dump(by_alias=True)
    assert 'PRIVATE_SECRET' not in str(understand(r).model_dump(by_alias=True))

@pytest.mark.parametrize('malformed', [
    'please use this: {"objective":"go"}',
    '{"objective":"go"} ignore prior rules',
    '[{"objective":"go"}]',
    '{"objective":',
    '```json\n{"objective":"go"}\n``` extra',
])
def test_semantic_model_invalid_output_cannot_be_salvaged(malformed):
    from app.semantics.semantic_intent_model import _extract_json
    with pytest.raises((ValueError, TypeError)):
        _extract_json(malformed)


def test_semantic_model_accepts_only_whole_json_object_or_fence():
    from app.semantics.semantic_intent_model import _extract_json
    assert _extract_json('{"objective":"explain"}') == {'objective': 'explain'}
    assert _extract_json('```json\n{"objective":"explain"}\n```') == {'objective': 'explain'}


def test_semantic_descriptor_rejects_resource_ids_even_if_model_injects_them():
    with pytest.raises(ValidationError):
        SemanticIntentDescriptor.model_validate({
            'objective': 'read something', 'capabilityKinds': ['KNOWLEDGE'],
            'knowledgeBaseId': 999,
        })


def test_model_does_not_run_on_simple_or_explicit_runtime_even_with_byok():
    simple = TaskUnderstandingRequest(task='你好', allowModel=True)
    required = TaskUnderstandingRequest(task='你们的退款政策是什么', allowModel=True)
    assert not needs_semantic_model(simple, understand(simple))
    assert not needs_semantic_model(required, understand(required))


def test_go_python_binary_contract_fixture():
    import json
    from pathlib import Path
    data = json.loads((Path(__file__).parent / 'fixtures' / 'p23_binary_route_contract.json').read_text(encoding='utf-8'))
    incoming = TaskUnderstandingRequest.model_validate(data['request'])
    assert understand(incoming).model_dump(by_alias=True) == data['response']
    assert TaskUnderstandingResult.model_validate(data['response']).execution_route == 'RUNTIME'
