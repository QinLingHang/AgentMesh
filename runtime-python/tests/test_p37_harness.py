"""P37 Agent Harness tests.

Covers: state machine, deterministic validators, loop detection, the guarded
tool executor across all four modes, structured diagnosis/recovery, the
supervisor summary/report, the OpenJiuwen internal-adapted executor and the
end-to-end OFF/OBSERVE parity requirement.
"""

import asyncio

import pytest

from app.config import settings

from app.harness import (
    HarnessConfig,
    HarnessSupervisor,
    HarnessTerminatedError,
    InvalidHarnessTransitionError,
)
from app.harness.contracts import (
    ALLOWED_TRANSITIONS,
    HarnessMode,
    HarnessRunState,
    ValidationResult,
)
from app.harness.loop import (
    LoopDetector,
    action_fingerprint,
)
from app.harness.recovery import (
    replan_decision,
    replan_prompt,
)
from app.harness.validators import (
    validate_final_result,
    validate_tool_input,
    validate_tool_output,
)
from app.models import (
    ModelGateway,
)
from app.models.providers import (
    MockModelProvider,
)
from app.schemas import (
    AgentProfile,
    RuntimeRequest,
)
from app.services import (
    RuntimeEngine,
    create_registry,
)
from app.tools import (
    ToolDefinition,
    ToolError,
    ToolErrorType,
    ToolRegistry,
)


def run(coro):
    return asyncio.run(coro)


def make_supervisor(
    mode: str,
    **kwargs,
) -> HarnessSupervisor:
    config = HarnessConfig(
        mode=mode,
        **kwargs,
    )

    return HarnessSupervisor(
        config,
        request_id="p37-test",
    )


# =========================================================
# State machine
# =========================================================


def test_state_machine_rejects_undefined_jumps():
    machine_states = HarnessRunState

    supervisor = make_supervisor("OBSERVE")

    state_machine = supervisor.state_machine

    assert (
        state_machine.state
        is machine_states.CREATED
    )

    state_machine.transition(
        machine_states.PRECHECK,
    )

    state_machine.transition(
        machine_states.EXECUTING,
    )

    # EXECUTING -> COMPLETED is not defined.
    with pytest.raises(
        InvalidHarnessTransitionError,
    ):
        state_machine.transition(
            machine_states.COMPLETED,
        )

    state_machine.transition(
        machine_states.RESULT_VALIDATING,
    )

    state_machine.transition(
        machine_states.COMPLETED,
    )

    timeline = [
        entry.state
        for entry in state_machine.timeline()
    ]

    assert timeline == [
        "CREATED",
        "PRECHECK",
        "EXECUTING",
        "RESULT_VALIDATING",
        "COMPLETED",
    ]


def test_state_machine_terminal_states_have_no_exits():
    for terminal in (
        HarnessRunState.COMPLETED,
        HarnessRunState.TERMINATED,
    ):
        assert len(ALLOWED_TRANSITIONS[terminal]) == 0


# =========================================================
# Validators
# =========================================================


def test_tool_input_validator_codes():
    schema = {
        "type": "object",
        "required": ["name", "level"],
        "properties": {
            "name": {"type": "string"},
            "level": {
                "type": "integer",
                "minimum": 1,
                "maximum": 5,
                "default": 3,
            },
            "role": {"enum": ["admin", "user"]},
        },
        "additionalProperties": False,
    }

    ok = validate_tool_input(
        {"name": "a", "level": 2, "role": "user"},
        schema,
    )

    assert ok.status == "PASS"

    # required + default available -> repairable code
    repairable = validate_tool_input(
        {"name": "a"},
        schema,
    )

    assert (
        repairable.code
        == "INPUT_MISSING_WITH_DEFAULT"
    )

    # enum violation
    enum_bad = validate_tool_input(
        {"name": "a", "level": 2, "role": "guest"},
        schema,
    )

    assert enum_bad.code == "INPUT_ENUM_INVALID"

    # range violation
    range_bad = validate_tool_input(
        {"name": "a", "level": 9, "role": "user"},
        schema,
    )

    assert range_bad.code == "INPUT_RANGE_INVALID"

    # additionalProperties violation
    unknown = validate_tool_input(
        {
            "name": "a",
            "level": 2,
            "role": "user",
            "extra": 1,
        },
        schema,
    )

    assert (
        unknown.code
        == "INPUT_UNKNOWN_FIELD"
    )

    # missing required without default wins
    unrepairable = validate_tool_input(
        {"level": 2, "role": "user"},
        schema,
    )

    assert (
        unrepairable.code
        == "INPUT_REQUIRED_MISSING"
    )


def test_tool_output_validator_not_configured_is_never_pass():
    result = validate_tool_output(
        {"any": "thing"},
        None,
    )

    assert result.status == "NOT_CONFIGURED"

    fail = validate_tool_output(
        {"orderId": "ORD-1"},
        {
            "type": "object",
            "required": ["status"],
            "properties": {"status": {"type": "string"}},
        },
    )

    assert fail.status == "FAIL"
    assert fail.code == "OUTPUT_SCHEMA_INVALID"
    assert fail.field_paths == ["$.status"]

    error_payload = validate_tool_output(
        {"error": {"message": "boom"}, "errorCode": "E1"},
        {"type": "object"},
    )

    assert error_payload.code == "TOOL_ERROR_RESULT"


def test_final_result_validator():
    empty = validate_final_result("", None)

    assert empty.code == "RESULT_EMPTY"

    basic = validate_final_result("ok answer", None)

    assert basic.status == "NOT_CONFIGURED"

    not_json = validate_final_result(
        "plain text",
        {"type": "object"},
    )

    assert not_json.code == "RESULT_NOT_JSON"

    ok = validate_final_result(
        '{"summary": "done", "steps": 3}',
        {
            "type": "object",
            "required": ["summary", "steps"],
            "properties": {
                "summary": {"type": "string"},
                "steps": {"type": "integer"},
            },
        },
    )

    assert ok.status == "PASS"

    incomplete = validate_final_result(
        '{"summary": "done"}',
        {
            "type": "object",
            "required": ["summary", "steps"],
            "properties": {
                "summary": {"type": "string"},
                "steps": {"type": "integer"},
            },
        },
    )

    assert incomplete.code == "RESULT_INCOMPLETE"


def test_loop_detector_threshold_semantics():
    detector = LoopDetector(threshold=2)

    fingerprint = action_fingerprint(
        action_type="tool_call",
        agent_name="a",
        tool_name="t",
        arguments={"x": 1},
        target_object_id=None,
    )

    assert not detector.would_repeat_without_progress(fingerprint, None)
    detector.register_output(fingerprint, None)

    # second identical no-progress action still allowed
    assert not detector.would_repeat_without_progress(fingerprint, None)
    detector.register_output(fingerprint, None)

    # third identical action must be blocked before executing
    assert detector.would_repeat_without_progress(fingerprint, None)

    # new progress resets
    detector.register_output(fingerprint, "v2")

    assert not detector.would_repeat_without_progress(fingerprint, "v2")


# =========================================================
# Guarded Tool Executor
# =========================================================


def _guarded(mode: str, **kwargs):
    supervisor = make_supervisor(mode, **kwargs)

    supervisor.begin_agent_attempt("tester")

    return supervisor


def test_guard_off_mode_is_not_installed():
    supervisor = make_supervisor("OFF")

    assert not supervisor.active


def test_guard_repair_args_with_schema_default():
    registry = ToolRegistry()

    seen = []

    registry.register(
        ToolDefinition(
            name="order",
            inputSchema={
                "type": "object",
                "required": ["orderId"],
                "properties": {
                    "orderId": {
                        "type": "string",
                        "default": "ORD-1001",
                    },
                },
            },
        ),
        lambda arguments: seen.append(dict(arguments)) or {"ok": True},
    )

    supervisor = _guarded("AUTO_REPAIR")

    result = run(
        supervisor.guarded_registry(registry).execute(
            "order",
            {},
        ),
    )

    assert result == {"ok": True}
    assert seen == [{"orderId": "ORD-1001"}]
    assert supervisor.budget.used_repairs == 1

    recovery_actions = [
        event.recovery.action
        for event in supervisor.events
        if event.recovery is not None
    ]

    assert recovery_actions == ["REPAIR_ARGS"]


def test_guard_blocks_unrepairable_input_before_call():
    registry = ToolRegistry()

    seen = []

    registry.register(
        ToolDefinition(
            name="order",
            inputSchema={
                "type": "object",
                "required": ["orderId"],
                "properties": {"orderId": {"type": "string"}},
            },
        ),
        lambda arguments: seen.append(arguments),
    )

    for mode in ("ENFORCE", "AUTO_REPAIR"):
        supervisor = _guarded(mode)

        with pytest.raises(HarnessTerminatedError) as raised:
            run(
                supervisor.guarded_registry(registry).execute(
                    "order",
                    {},
                ),
            )

        assert "INPUT_VALIDATION_INPUT_REQUIRED_MISSING" in str(
            raised.value
        )

        assert seen == []
        assert (
            supervisor.state_machine.state
            is HarnessRunState.TERMINATED
        )


def test_observe_records_but_never_blocks():
    registry = ToolRegistry()

    seen = []

    registry.register(
        ToolDefinition(
            name="order",
            inputSchema={
                "type": "object",
                "required": ["orderId"],
                "properties": {"orderId": {"type": "string"}},
            },
        ),
        lambda arguments: seen.append(dict(arguments)) or dict(arguments),
    )

    supervisor = _guarded("OBSERVE")

    # Invalid input: the legacy deterministic schema error is preserved...
    with pytest.raises(ToolError) as raised:
        run(
            supervisor.guarded_registry(registry).execute(
                "order",
                {},
            ),
        )

    assert (
        raised.value.error_type
        is ToolErrorType.INVALID_ARGUMENTS
    )

    assert seen == []

    failures = [
        event
        for event in supervisor.events
        if event.validation is not None
        and event.validation.status == "FAIL"
    ]

    assert failures

    # ...and a valid call behaves exactly like the legacy path.
    result = run(
        supervisor.guarded_registry(registry).execute(
            "order",
            {"orderId": "ORD-1"},
        ),
    )

    assert seen == [{"orderId": "ORD-1"}]

    assert result["orderId"] == "ORD-1"


def test_guard_output_schema_blocks_invalid_result():
    registry = ToolRegistry()

    registry.register(
        ToolDefinition(
            name="order",
            outputSchema={
                "type": "object",
                "required": ["status"],
                "properties": {"status": {"type": "string"}},
            },
        ),
        lambda arguments: {"orderId": "ORD-1"},
    )

    for mode in ("ENFORCE", "AUTO_REPAIR"):
        supervisor = _guarded(mode)

        with pytest.raises(HarnessTerminatedError) as raised:
            run(
                supervisor.guarded_registry(registry).execute(
                    "order",
                    {},
                ),
            )

        assert "OUTPUT_SCHEMA_INVALID" in str(raised.value)

    # OBSERVE returns the raw invalid result unchanged.
    supervisor = _guarded("OBSERVE")

    raw = run(
        supervisor.guarded_registry(registry).execute(
            "order",
            {},
        ),
    )

    assert raw == {"orderId": "ORD-1"}


def test_guard_retries_read_only_timeout_within_budget():
    calls = {"n": 0}

    async def flaky(arguments):
        calls["n"] += 1

        if calls["n"] == 1:
            await asyncio.sleep(0.05)

        return {"ok": True}

    registry = ToolRegistry(timeout=0.01)

    registry.register(
        ToolDefinition(
            name="flaky",
            sideEffectRisk="READ_ONLY",
        ),
        flaky,
    )

    supervisor = _guarded("AUTO_REPAIR")

    result = run(
        supervisor.guarded_registry(registry).execute(
            "flaky",
            {},
        ),
    )

    assert result == {"ok": True}
    assert calls["n"] == 2
    assert supervisor.budget.used_tool_retries == 1


def test_guard_terminates_on_unknown_write_outcome():
    calls = {"n": 0}

    async def slow_write(arguments):
        calls["n"] += 1
        await asyncio.sleep(0.05)

    registry = ToolRegistry(timeout=0.01)

    registry.register(
        ToolDefinition(
            name="write_thing",
            sideEffectRisk="NON_IDEMPOTENT_WRITE",
        ),
        slow_write,
    )

    supervisor = _guarded("AUTO_REPAIR")

    with pytest.raises(HarnessTerminatedError) as raised:
        run(
            supervisor.guarded_registry(registry).execute(
                "write_thing",
                {},
            ),
        )

    assert "TOOL_OUTCOME_UNKNOWN" in str(raised.value)

    # exactly one attempt: no automatic retry of a sent write
    assert calls["n"] == 1

    diagnosis = raised.value.diagnosis

    assert diagnosis is not None
    assert not diagnosis.retryable
    assert diagnosis.recommended_action == "TERMINATE"


def test_guard_fallback_tool_on_invalid_output():
    registry = ToolRegistry()

    schema_bad = {
        "type": "object",
        "required": ["status"],
        "properties": {"status": {"type": "string"}},
    }

    registry.register(
        ToolDefinition(
            name="primary",
            outputSchema=schema_bad,
            fallbackToolId="primary_v2",
        ),
        lambda arguments: {"nope": True},
    )

    registry.register(
        ToolDefinition(
            name="primary_v2",
            outputSchema=schema_bad,
        ),
        lambda arguments: {"status": "OK"},
    )

    supervisor = _guarded("AUTO_REPAIR")

    result = run(
        supervisor.guarded_registry(registry).execute(
            "primary",
            {},
        ),
    )

    assert result == {"status": "OK"}
    assert supervisor.budget.used_repairs == 1

    recovery_actions = [
        event.recovery.action
        for event in supervisor.events
        if event.recovery is not None
    ]

    assert recovery_actions == ["FALLBACK"]


def test_guard_terminates_loop_at_threshold():
    registry = ToolRegistry()

    registry.register(
        ToolDefinition(
            name="stuck",
        ),
        lambda arguments: {"same": True},
    )

    supervisor = _guarded("AUTO_REPAIR")

    guarded = supervisor.guarded_registry(registry)

    run(guarded.execute("stuck", {"q": 1}))
    run(guarded.execute("stuck", {"q": 1}))

    with pytest.raises(HarnessTerminatedError) as raised:
        run(guarded.execute("stuck", {"q": 1}))

    assert "LOOP_DETECTED" in str(raised.value)
    assert raised.value.diagnosis.category == "LOOP"

    # parameter change would have produced a new fingerprint
    other = make_supervisor("AUTO_REPAIR")

    other.begin_agent_attempt("tester")

    other_guarded = other.guarded_registry(registry)

    run(other_guarded.execute("stuck", {"q": 1}))
    run(other_guarded.execute("stuck", {"q": 2}))

    assert (
        other.state_machine.state
        is not HarnessRunState.TERMINATED
    )


def test_guard_step_budget_exhaustion():
    registry = ToolRegistry()

    registry.register(
        ToolDefinition(name="t"),
        lambda arguments: {"ok": True},
    )

    # Budget: 1 agent attempt + 1 tool call. The next tool call terminates.
    supervisor = make_supervisor(
        "ENFORCE",
        maxSteps=2,
    )

    supervisor.begin_agent_attempt("tester")

    guarded = supervisor.guarded_registry(registry)

    run(guarded.execute("t", {}))

    with pytest.raises(HarnessTerminatedError) as raised:
        run(guarded.execute("t", {}))

    assert "STEP_BUDGET_EXHAUSTED" in str(raised.value)


# =========================================================
# Supervisor reporting
# =========================================================


def test_supervisor_finish_summary_and_report():
    supervisor = _guarded("OBSERVE")

    supervisor.emit(
        "precheck",
        validation=ValidationResult(
            validator="Test.v1",
            status="FAIL",
            code="X",
        ),
    )

    summary, report = supervisor.finish(
        business_completed=True,
    )

    assert summary.mode == "OBSERVE"
    assert summary.outcome == "OBSERVED_ISSUES"
    assert summary.validation_failures >= 1

    assert report.config_snapshot["mode"] == "OBSERVE"
    assert report.metrics.validation_failures >= 1
    assert report.events

    sequences = [event.sequence for event in report.events]

    assert sequences == sorted(sequences)


def test_replan_decision_policy():
    failing = ValidationResult(
        validator="ResultValidator.v1",
        status="FAIL",
        code="RESULT_INCOMPLETE",
    )

    allowed, reason = replan_decision(
        validation=failing,
        protocol="internal",
        can_repair=True,
        replay_safe=True,
    )

    assert allowed

    blocked_budget, _ = replan_decision(
        validation=failing,
        protocol="internal",
        can_repair=False,
        replay_safe=True,
    )

    assert not blocked_budget

    blocked_side_effect, reason = replan_decision(
        validation=failing,
        protocol="internal",
        can_repair=True,
        replay_safe=False,
    )

    assert not blocked_side_effect
    assert "side-effect" in reason

    blocked_remote, _ = replan_decision(
        validation=failing,
        protocol="http",
        can_repair=True,
        replay_safe=True,
    )

    assert not blocked_remote

    prompt = replan_prompt(
        "do the thing",
        "partial",
        failing,
    )

    assert "RESULT_INCOMPLETE" in prompt
    assert "do the thing" in prompt


# =========================================================
# OpenJiuwen executor
# =========================================================


def test_openjiuwen_executor_runs_real_tool_through_registry():
    async def scenario():
        registry = await create_registry()

        try:
            agent = AgentProfile(
                id=7,
                name="JiuwenBot",
                endpoint="internal://jiuwen",
                protocol="internal",
                capabilities=["general"],
                executorType="openjiuwen",
            )

            tool_registry = ToolRegistry()

            tool_registry.register(
                ToolDefinition(name="get_order"),
                lambda arguments: {
                    "orderId": "ORD-1001",
                    "status": "PAID",
                },
            )

            step_events = []

            tool_events = []

            request = _build_executor_request(
                agent,
                tool_registry,
                on_runtime_event=step_events.append,
                on_tool_event=tool_events.append,
            )

            # Routing: protocol=internal + executorType=openjiuwen resolves
            # to the standalone OpenJiuwen executor, not agent.internal.
            from app.agents import (
                AgentExecutorResolver,
                OpenJiuwenAgentExecutor,
            )

            resolver = AgentExecutorResolver(registry)

            executor = resolver.resolve(agent)

            assert executor.manifest.id == "agent.openjiuwen"
            assert isinstance(
                executor.executor,
                OpenJiuwenAgentExecutor,
            )

            result = await executor.execute(request)

            assert "[Mock Answer] Tool observation" in result.content
            assert result.metadata["executorType"] == "openjiuwen"
            assert result.metadata["protocol"] == "internal"

            titles = [event["title"] for event in step_events]

            assert titles[0] == "OpenJiuwen Agent Started"
            assert titles[-1] == "OpenJiuwen Agent Completed"

            # The tool call went through the tool bridge into the registry.
            tool_titles = [
                event["title"] for event in tool_events
            ]

            assert "Tool Started" in tool_titles
            assert "Tool Completed" in tool_titles
        finally:
            await registry.stop_all()

    run(scenario())


def test_openjiuwen_routing_matrix():
    async def scenario():
        registry = await create_registry()

        try:
            from app.agents import (
                AgentExecutorResolutionError,
                AgentExecutorResolver,
                OpenJiuwenAgentExecutor,
            )

            resolver = AgentExecutorResolver(registry)

            # internal + native (default) keeps the existing executor.
            native = AgentProfile(
                id=1,
                name="Native",
                endpoint="internal://native",
                protocol="internal",
                capabilities=["general"],
            )

            from app.plugins import InternalAgentPlugin

            assert isinstance(
                resolver.resolve(native),
                InternalAgentPlugin,
            )

            # protocol != internal with openjiuwen -> explicit error.
            http_openjiuwen = AgentProfile(
                id=2,
                name="Remote",
                endpoint="https://example.com",
                protocol="http",
                capabilities=["general"],
                executorType="openjiuwen",
            )

            with pytest.raises(
                AgentExecutorResolutionError,
                match="only supported with protocol 'internal'",
            ):
                resolver.resolve(http_openjiuwen)

            # unknown executor type -> explicit error.
            weird = native.model_copy(
                update={"executor_type": "mystery"},
            )

            with pytest.raises(
                AgentExecutorResolutionError,
                match="unsupported agent executor type",
            ):
                resolver.resolve(weird)
        finally:
            await registry.stop_all()

    run(scenario())


def _fake_model_runtime():
    from app.models.runtime import ResolvedModelRuntime

    return ResolvedModelRuntime(
        runtime_id="test",
        gateway=ModelGateway(
            MockModelProvider(),
            timeout=2,
            max_retries=0,
        ),
        gateway_provider="mock",
        declared_provider="mock",
        model="mock",
        vision_model=None,
        plugin=None,
    )


def _build_executor_request(
    agent,
    tool_registry,
    on_runtime_event=None,
    on_tool_event=None,
):
    from app.agents import AgentExecutionRequest

    return AgentExecutionRequest(
        agent=agent,
        capability="general",
        task="get order",
        tool_registry=tool_registry,
        on_runtime_event=on_runtime_event,
        on_tool_event=on_tool_event,
        model_runtime=_fake_model_runtime(),
    )


# =========================================================
# End-to-end engine: OFF vs OBSERVE parity, AUTO_REPAIR report
# =========================================================


def _engine_request(
    request_id: str,
    task: str,
    harness_config=None,
    tools=None,
):
    agent = AgentProfile(
        id=1,
        name="General",
        endpoint="internal://general",
        protocol="internal",
        capabilities=["general"],
    )

    return RuntimeRequest(
        user_id=1,
        request_id=request_id,
        task=task,
        agents=[agent],
        tools=tools or [],
        harnessConfig=harness_config,
    )


def test_engine_harness_observe_parity_and_off_backward_compatibility():
    async def scenario():
        registry = await create_registry()

        try:
            engine = RuntimeEngine(registry)

            off = await engine.run(
                _engine_request("off", "get order"),
            )

            assert off.harness_summary is None
            assert off.harness_report is None

            observe_config = HarnessConfig(mode="OBSERVE")

            observe = await engine.run(
                _engine_request(
                    "observe",
                    "get order",
                    harness_config=observe_config,
                ),
            )

            assert observe.answer == off.answer
            assert observe.harness_summary is not None
            assert observe.harness_summary.mode == "OBSERVE"
            assert observe.harness_report is not None
            assert observe.harness_report.events
            assert observe.harness_report.config_snapshot["mode"] == "OBSERVE"
        finally:
            await registry.stop_all()

    run(scenario())


def test_engine_auto_repair_normal_task_has_no_repairs():
    async def scenario():
        registry = await create_registry()

        try:
            engine = RuntimeEngine(registry)

            config = HarnessConfig(mode="AUTO_REPAIR")

            result = await engine.run(
                _engine_request(
                    "auto",
                    "get order",
                    harness_config=config,
                ),
            )

            assert result.answer
            assert (
                result.harness_summary.outcome
                == "COMPLETED"
            )
            assert result.harness_summary.repairs == 0

            # the tool call went through the guard
            harness_events = [
                event
                for event in result.trace
                if event.kind == "harness"
            ]

            assert harness_events
        finally:
            await registry.stop_all()

    run(scenario())


def test_engine_invalid_mode_is_rejected_by_contract():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        HarnessConfig(mode="SUPER_MODE")
