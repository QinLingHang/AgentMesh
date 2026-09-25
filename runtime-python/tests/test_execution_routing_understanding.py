"""Binary Execution Routing route contracts: no concrete capability choice at preflight.

These are curated unit examples, NOT the independently frozen real-stack QA set.
"""
import pytest
from pydantic import ValidationError
from app.semantics.execution_routing import (
    ExecutionRoutingRequest, ExecutionRoutingResult, decide_execution_route, needs_semantic_routing_model,
)
from app.semantics.execution_routing_model import SemanticIntentDescriptor


def route(text, **options):
    return decide_execution_route(ExecutionRoutingRequest.model_validate({"task": text, **options}))


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
    request = ExecutionRoutingRequest(task='我的订单状态')
    assert 'authorizedCapabilities' not in request.model_dump(by_alias=True)
    with pytest.raises(ValidationError):
        ExecutionRoutingRequest.model_validate({'task': '你好', 'authorizedCapabilities': [{'ref': 'TOOL:7'}]})


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
    req = ExecutionRoutingRequest(task='解释一下 Go slice')
    baseline = decide_execution_route(req)
    injected = SemanticIntentDescriptor.model_validate({
        'objective': '解释一下 Go slice', 'capabilityKinds': ['TOOL'],
    })
    refined = decide_execution_route(req, descriptor=injected)
    assert baseline.execution_route == 'FAST_PATH'
    assert refined.execution_route == 'RUNTIME'
    assert 'matchedCapabilityRefs' not in refined.model_dump(by_alias=True)


def test_descriptor_cannot_override_rag_off():
    req = ExecutionRoutingRequest(task='解释一下 Go slice', ragMode='OFF')
    descriptor = SemanticIntentDescriptor.model_validate({
        'objective': '解释一下 Go slice', 'knowledgeDependency': 'REQUIRED',
    })
    d = decide_execution_route(req, descriptor=descriptor)
    assert d.disposition == 'CLARIFY'
    assert d.execution_route == 'RUNTIME'


def test_model_failure_fallback_cannot_downgrade_unknown():
    req = ExecutionRoutingRequest(task='这个怎么样？', allowModel=True)
    baseline = decide_execution_route(req)
    assert baseline.execution_route == 'RUNTIME'
    assert baseline.model_calls == 0
    assert needs_semantic_routing_model(req, baseline)
    assert not needs_semantic_routing_model(req.model_copy(update={'allow_model': False}), baseline)


def test_schema_fail_closed_and_no_extra_model_fields():
    for payload in [
        {'schemaVersion': 'legacy-routing.v1', 'task': '你好'},
        {'task': '你好', 'projectId': 777},
        {'task': '你好', 'authorizedCapabilities': [{'ref': 'KNOWLEDGE:1'}]},
    ]:
        with pytest.raises(ValidationError):
            ExecutionRoutingRequest.model_validate(payload)
    with pytest.raises(ValidationError):
        ExecutionRoutingResult.model_validate({
            'executionRoute': 'INVALID_ROUTE', 'knowledgeDependency': 'NONE',
        })


def test_model_credentials_not_serialized_in_response_or_dump():
    r = ExecutionRoutingRequest.model_validate({
        'task': '这个是什么？',
        'projectModel': {
            'provider': 'openai-compatible', 'baseUrl': 'http://localhost:1234',
            'modelName': 'model', 'apiKey': 'PRIVATE_SECRET',
        },
    })
    assert 'PRIVATE_SECRET' not in str(r.model_dump(by_alias=True))
    assert 'projectModel' not in r.model_dump(by_alias=True)
    assert 'PRIVATE_SECRET' not in str(decide_execution_route(r).model_dump(by_alias=True))

@pytest.mark.parametrize('malformed', [
    'please use this: {"objective":"go"}',
    '{"objective":"go"} ignore prior rules',
    '[{"objective":"go"}]',
    '{"objective":',
    '```json\n{"objective":"go"}\n``` extra',
])
def test_semantic_model_invalid_output_cannot_be_salvaged(malformed):
    from app.semantics.execution_routing_model import _extract_json
    with pytest.raises((ValueError, TypeError)):
        _extract_json(malformed)


def test_semantic_model_accepts_only_whole_json_object_or_fence():
    from app.semantics.execution_routing_model import _extract_json
    assert _extract_json('{"objective":"explain"}') == {'objective': 'explain'}
    assert _extract_json('```json\n{"objective":"explain"}\n```') == {'objective': 'explain'}


def test_semantic_descriptor_rejects_resource_ids_even_if_model_injects_them():
    with pytest.raises(ValidationError):
        SemanticIntentDescriptor.model_validate({
            'objective': 'read something', 'capabilityKinds': ['KNOWLEDGE'],
            'knowledgeBaseId': 999,
        })


def test_model_does_not_run_on_simple_or_explicit_runtime_even_with_byok():
    simple = ExecutionRoutingRequest(task='你好', allowModel=True)
    required = ExecutionRoutingRequest(task='你们的退款政策是什么', allowModel=True)
    assert not needs_semantic_routing_model(simple, decide_execution_route(simple))
    assert not needs_semantic_routing_model(required, decide_execution_route(required))


def test_go_python_binary_contract_fixture():
    import json
    from pathlib import Path
    data = json.loads((Path(__file__).parent / 'fixtures' / 'execution_route_contract.json').read_text(encoding='utf-8'))
    incoming = ExecutionRoutingRequest.model_validate(data['request'])
    assert decide_execution_route(incoming).model_dump(by_alias=True) == data['response']
    assert ExecutionRoutingResult.model_validate(data['response']).execution_route == 'RUNTIME'


def _continuation_descriptor(intent: str, *, references=True, fresh=False, action=False, kinds=None, knowledge='NONE'):
    return SemanticIntentDescriptor.model_validate({
        'objective': 'continue the prior answer',
        'capabilityKinds': kinds or [],
        'knowledgeDependency': knowledge,
        'continuationIntent': intent,
        'referencesPrevious': references,
        'needsFreshData': fresh,
        'externalActionRequired': action,
    })


def test_contextual_continuation_model_can_keep_explanation_on_fast_path():
    req = ExecutionRoutingRequest.model_validate({
        'task': '继续说，不太懂',
        'continuationState': 'CHAT',
        'previousTurn': {'exists': True, 'executionRoute': 'FAST_PATH', 'status': 'COMPLETED', 'runtimePhase': 'interactive_stream'},
    })
    baseline = decide_execution_route(req)
    assert baseline.execution_route == 'RUNTIME'
    refined = decide_execution_route(req, descriptor=_continuation_descriptor('EXPLAIN_PREVIOUS'))
    assert refined.execution_route == 'FAST_PATH'
    assert refined.analysis_source == 'MODEL'


def test_contextual_continuation_does_not_reuse_knowledge_as_unverified_chat():
    req = ExecutionRoutingRequest.model_validate({
        'task': '简单点说，我还是没懂',
        'continuationState': 'CHAT',
        'previousTurn': {
            'exists': True, 'executionRoute': 'RUNTIME', 'status': 'COMPLETED',
            'runtimePhase': 'completed', 'knowledgeUsed': True,
        },
    })
    refined = decide_execution_route(req, descriptor=_continuation_descriptor('EXPLAIN_PREVIOUS'))
    assert refined.execution_route == 'RUNTIME'


def test_tool_result_explanation_can_be_fast_but_refresh_stays_runtime():
    base = {
        'continuationState': 'CHAT',
        'previousTurn': {
            'exists': True, 'executionRoute': 'RUNTIME', 'status': 'COMPLETED',
            'runtimePhase': 'completed', 'toolUsed': True,
        },
    }
    explain = ExecutionRoutingRequest.model_validate({'task': '这个状态是什么意思？', **base})
    explained = decide_execution_route(explain, descriptor=_continuation_descriptor('EXPLAIN_PREVIOUS'))
    assert explained.execution_route == 'FAST_PATH'

    refresh = ExecutionRoutingRequest.model_validate({'task': '现在呢，再查一下', **base})
    refreshed = decide_execution_route(
        refresh,
        descriptor=_continuation_descriptor('REFRESH_DATA', fresh=True, kinds=['TOOL']),
    )
    assert refreshed.execution_route == 'RUNTIME'


def test_previous_turn_metadata_triggers_bounded_semantic_understanding_for_short_followup():
    req = ExecutionRoutingRequest.model_validate({
        'task': '为什么？',
        'allowModel': True,
        'previousTurn': {'exists': True, 'executionRoute': 'FAST_PATH', 'status': 'COMPLETED'},
    })
    baseline = decide_execution_route(req)
    assert baseline.execution_route == 'RUNTIME'
    assert needs_semantic_routing_model(req, baseline)


def test_general_new_fact_followup_can_stay_fast_after_fast_path_answer():
    req = ExecutionRoutingRequest.model_validate({
        'task': '为什么 append 有时候会影响原来的 slice？',
        'previousTurn': {'exists': True, 'executionRoute': 'FAST_PATH', 'status': 'COMPLETED'},
    })
    refined = decide_execution_route(req, descriptor=_continuation_descriptor('NEW_FACT_FOLLOWUP'))
    assert refined.execution_route == 'FAST_PATH'


def test_new_fact_followup_after_knowledge_answer_stays_runtime():
    req = ExecutionRoutingRequest.model_validate({
        'task': '那韩国呢？',
        'previousTurn': {
            'exists': True, 'executionRoute': 'RUNTIME', 'status': 'COMPLETED',
            'knowledgeUsed': True,
        },
    })
    refined = decide_execution_route(req, descriptor=_continuation_descriptor('NEW_FACT_FOLLOWUP'))
    assert refined.execution_route == 'RUNTIME'


def test_semantic_model_unavailable_uses_only_trusted_fast_path_continuation_fallback():
    from app.semantics.execution_routing import trusted_fast_path_continuation_fallback
    req = ExecutionRoutingRequest.model_validate({
        'task': '继续说，不太懂',
        'continuationState': 'CHAT',
        'previousTurn': {
            'exists': True, 'executionRoute': 'FAST_PATH', 'status': 'COMPLETED',
            'runtimePhase': 'interactive_stream', 'knowledgeUsed': False,
            'toolUsed': False, 'mcpUsed': False,
        },
    })
    baseline = decide_execution_route(req)
    assert baseline.execution_route == 'RUNTIME'
    fallback = trusted_fast_path_continuation_fallback(req, baseline)
    assert fallback.execution_route == 'FAST_PATH'
    assert fallback.analysis_source == 'RULE'
    assert fallback.reason_codes == ['TRUSTED_FAST_PATH_CONTINUATION_FALLBACK']


def test_trusted_fast_path_continuation_fallback_never_handles_new_action_or_fresh_data():
    from app.semantics.execution_routing import trusted_fast_path_continuation_fallback
    common = {
        'continuationState': 'CHAT',
        'previousTurn': {
            'exists': True, 'executionRoute': 'FAST_PATH', 'status': 'COMPLETED',
            'runtimePhase': 'interactive_stream', 'knowledgeUsed': False,
            'toolUsed': False, 'mcpUsed': False,
        },
    }
    for task in ('继续执行代码', '现在呢，再查一下', '刷新一下最新状态'):
        req = ExecutionRoutingRequest.model_validate({'task': task, **common})
        baseline = decide_execution_route(req)
        assert trusted_fast_path_continuation_fallback(req, baseline).execution_route == 'RUNTIME'


def test_trusted_fast_path_continuation_fallback_never_reuses_knowledge_or_tool_turn():
    from app.semantics.execution_routing import trusted_fast_path_continuation_fallback
    for field in ('knowledgeUsed', 'toolUsed', 'mcpUsed'):
        previous = {
            'exists': True, 'executionRoute': 'FAST_PATH', 'status': 'COMPLETED',
            'runtimePhase': 'interactive_stream', 'knowledgeUsed': False,
            'toolUsed': False, 'mcpUsed': False, field: True,
        }
        req = ExecutionRoutingRequest.model_validate({
            'task': '继续说，不太懂', 'continuationState': 'CHAT', 'previousTurn': previous,
        })
        baseline = decide_execution_route(req)
        assert trusted_fast_path_continuation_fallback(req, baseline).execution_route == 'RUNTIME'

def test_explicit_capability_prohibition_is_structured_policy_not_permission():
    from app.semantics import analyze_task_semantics

    semantic = analyze_task_semantics("请分析这个请求，但不需要 MCP，也不要使用工具。")
    assert set(semantic.forbidden_capabilities) == {"mcp", "tool"}
    assert "mcp" not in {item.casefold() for item in semantic.required_capabilities}
    assert "tool" not in {item.casefold() for item in semantic.required_capabilities}



def test_inline_summary_does_not_execute_source_material_keywords():
    d = route('总结这段话：Agent Runtime 负责承载智能体执行，并协调模型调用、工具调用、状态管理与任务流程。')
    assert d.execution_route == 'FAST_PATH'


def test_explanation_only_programming_question_stays_fast_path():
    d = route('说一下 Go map 和 slice 的一个核心区别。')
    assert d.execution_route == 'FAST_PATH'


def test_new_fact_followup_ignores_non_governed_descriptor_noise_after_fast_path():
    req = ExecutionRoutingRequest.model_validate({
        'task': '为什么 append 有时候会影响原来的 slice？',
        'continuationState': 'CHAT',
        'previousTurn': {
            'exists': True, 'executionRoute': 'FAST_PATH', 'status': 'COMPLETED',
            'knowledgeUsed': False, 'toolUsed': False, 'mcpUsed': False,
        },
    })
    descriptor = _continuation_descriptor('NEW_FACT_FOLLOWUP')
    descriptor.capability_kinds = ['AGENT']
    descriptor.multi_step = True
    refined = decide_execution_route(req, descriptor=descriptor)
    assert refined.execution_route == 'FAST_PATH'



def test_implicit_conceptual_followup_inherits_capability_free_fast_path_without_lexical_chat_state():
    req = ExecutionRoutingRequest.model_validate({
        'task': '为什么 append 有时候会影响原来的 slice？',
        'continuationState': 'NONE',
        'previousTurn': {
            'exists': True, 'executionRoute': 'FAST_PATH', 'status': 'COMPLETED',
            'knowledgeUsed': False, 'toolUsed': False, 'mcpUsed': False,
        },
    })
    descriptor = _continuation_descriptor('NEW_FACT_FOLLOWUP', references=False)
    descriptor.capability_kinds = ['AGENT']
    descriptor.multi_step = True
    refined = decide_execution_route(req, descriptor=descriptor)
    assert refined.execution_route == 'FAST_PATH'
    assert refined.capability_required is False


def test_self_contained_concept_question_stays_fast_even_when_previous_turn_exists():
    req = ExecutionRoutingRequest.model_validate({
        'task': '为什么 append 有时候会影响原来的 slice？',
        'allowModel': True,
        'continuationState': 'NONE',
        'previousTurn': {
            'exists': True, 'executionRoute': 'FAST_PATH', 'status': 'COMPLETED',
            'knowledgeUsed': False, 'toolUsed': False, 'mcpUsed': False,
        },
    })
    baseline = decide_execution_route(req)
    assert baseline.execution_route == 'FAST_PATH'
    assert baseline.capability_required is False
    assert not needs_semantic_routing_model(req, baseline)




def test_anaphoric_followup_uses_model_but_does_not_require_model_to_repeat_reference_bit():
    req = ExecutionRoutingRequest.model_validate({
        'task': '那它和数组最大的本质区别呢？',
        'allowModel': True,
        'continuationState': 'NONE',
        'previousTurn': {
            'exists': True, 'executionRoute': 'FAST_PATH', 'status': 'COMPLETED',
            'knowledgeUsed': False, 'toolUsed': False, 'mcpUsed': False,
        },
    })
    baseline = decide_execution_route(req)
    assert baseline.execution_route == 'RUNTIME'
    assert needs_semantic_routing_model(req, baseline)

    descriptor = SemanticIntentDescriptor.model_validate({
        'objective': 'compare the referenced concept with arrays',
        'capabilityKinds': [],
        'knowledgeDependency': 'NONE',
        'multiStep': False,
        'hasDependencies': False,
        'hasConditionalEffects': False,
        'requestedEffects': [],
        'continuationIntent': 'NONE',
        'referencesPrevious': False,
        'needsFreshData': False,
        'externalActionRequired': False,
        'unknowns': [],
        'reasonCodes': [],
    })
    refined = decide_execution_route(req, descriptor=descriptor)
    assert refined.execution_route == 'FAST_PATH'
    assert refined.analysis_source == 'MODEL'



@pytest.mark.parametrize('task, model_unknown', [
    ('那它呢？', 'subject'),
    ('这个具体是什么意思？', 'referenced concept'),
    ('它为什么会这样？', 'it'),
])
def test_safe_anaphoric_followup_resolves_free_form_referent_from_trusted_chat(task, model_unknown):
    req = ExecutionRoutingRequest.model_validate({
        'task': task,
        'allowModel': True,
        'continuationState': 'NONE',
        'previousTurn': {
            'exists': True, 'executionRoute': 'FAST_PATH', 'status': 'COMPLETED',
            'knowledgeUsed': False, 'toolUsed': False, 'mcpUsed': False,
        },
    })
    descriptor = SemanticIntentDescriptor.model_validate({
        'objective': 'compare the referenced concept with arrays',
        'capabilityKinds': [],
        'knowledgeDependency': 'NONE',
        'multiStep': False,
        'hasDependencies': False,
        'hasConditionalEffects': False,
        'requestedEffects': [],
        'continuationIntent': 'NONE',
        'referencesPrevious': False,
        'needsFreshData': False,
        'externalActionRequired': False,
        'unknowns': [model_unknown],
        'reasonCodes': [],
    })
    refined = decide_execution_route(req, descriptor=descriptor)
    assert refined.execution_route == 'FAST_PATH'
    assert refined.disposition == 'EXECUTE'
    assert refined.analysis_source == 'MODEL'


def test_anaphoric_external_delete_with_unknown_target_still_requires_clarification():
    req = ExecutionRoutingRequest.model_validate({
        'task': '把它删掉',
        'allowModel': True,
        'continuationState': 'NONE',
        'previousTurn': {
            'exists': True, 'executionRoute': 'FAST_PATH', 'status': 'COMPLETED',
            'knowledgeUsed': False, 'toolUsed': False, 'mcpUsed': False,
        },
    })
    baseline = decide_execution_route(req)
    assert baseline.execution_route == 'RUNTIME'
    assert baseline.disposition == 'CLARIFY'
    assert baseline.reason_codes == ['AMBIGUOUS_RUNTIME_TARGET']

def test_anaphoric_continuation_cannot_be_short_circuited_before_semantic_model():
    from app.semantics.execution_routing import trusted_fast_path_continuation_fallback
    req = ExecutionRoutingRequest.model_validate({
        'task': '那它和数组最大的本质区别呢？',
        'allowModel': True,
        'continuationState': 'NONE',
        'previousTurn': {
            'exists': True, 'executionRoute': 'FAST_PATH', 'status': 'COMPLETED',
            'knowledgeUsed': False, 'toolUsed': False, 'mcpUsed': False,
        },
    })
    baseline = decide_execution_route(req)
    assert baseline.execution_route == 'RUNTIME'
    assert needs_semantic_routing_model(req, baseline)
    assert trusted_fast_path_continuation_fallback(req, baseline).execution_route == 'RUNTIME'
