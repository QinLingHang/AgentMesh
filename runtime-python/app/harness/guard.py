"""Guarded Tool Executor (P37 §7.5).

A thin wrapper around the existing ToolRegistry: tool discovery, governance
and adapters are untouched. Internal / HTTP / MCP tools that run through the
registry all pass the same guard sequence:

    governance check -> loop check -> input validation -> call ->
    error normalization -> output validation -> fingerprint/budget/events.

Mode semantics:
    OFF           guard never installed.
    OBSERVE       record everything, change nothing (same calls, same results,
                  same exceptions).
    ENFORCE       block defined failures before they reach the tool or before
                  an invalid result is returned to the agent.
    AUTO_REPAIR   additionally run whitelisted recovery inside the unified
                  budget (defaults/aliases repair, read-only or idempotent
                  retry, explicit fallback).
"""

import json

from time import (
    perf_counter,
)

from typing import (
    Any,
)

from app.harness.contracts import (
    HarnessRecovery,
    HarnessRunState,
    HarnessTerminatedError,
    SideEffectRisk,
)
from app.harness.diagnosis import (
    diagnose_loop,
    diagnose_tool_error,
    diagnose_tool_input_failure,
    diagnose_tool_output_failure,
    diagnose_unknown,
)
from app.harness.loop import (
    PROGRESS_MARKER_KEY,
    action_fingerprint,
    extract_progress_marker,
)
from app.harness.validators import (
    TOOL_INPUT_VALIDATOR,
    TOOL_OUTPUT_VALIDATOR,
    validate_step,
    validate_tool_input,
    validate_tool_output,
)
from app.tools.contracts import (
    ToolDefinition,
    ToolError,
    ToolErrorType,
)
from app.tools.registry import (
    ToolRegistry,
)


_IDEMPOTENCY_KEY = "idempotencyKey"

# Errors raised at or after the adapter boundary: the request was sent or
# its outcome is unknown. NOT_FOUND / PERMISSION_DENIED / REQUIRES_APPROVAL /
# INVALID_ARGUMENTS are pre-adapter rejections where nothing was sent.
_SENT_OR_UNKNOWN_ERRORS = {
    ToolErrorType.TIMEOUT,
    ToolErrorType.UNAVAILABLE,
    ToolErrorType.EXECUTION_FAILED,
}


def _side_effect_risk(
    tool: ToolDefinition,
) -> SideEffectRisk:
    try:
        return SideEffectRisk(
            tool.side_effect_risk,
        )

    except ValueError:
        return SideEffectRisk.UNKNOWN


def apply_argument_repair(
    arguments: dict[str, Any],
    tool: ToolDefinition,
) -> tuple[
    dict[str, Any],
    list[str],
]:
    """REPAIR_ARGS: schema defaults and explicit aliases only.

    The repair never guesses a business value or changes user intent: every
    injected value comes verbatim from the tool's declared contract.
    """

    repaired = dict(
        arguments,
    )

    notes: list[str] = []

    properties = (
        tool.input_schema.get(
            "properties",
        )
        or {}
    )

    aliases = (
        tool.argument_aliases
        or {}
    )

    for alias, canonical in aliases.items():
        if (
            alias in repaired
            and canonical
            not in repaired
        ):
            repaired[canonical] = repaired.pop(
                alias,
            )

            notes.append(
                f"alias {alias}->{canonical}",
            )

    required = (
        tool.input_schema.get(
            "required",
        )
        or []
    )

    for name in required:
        if name in repaired:
            continue

        spec = properties.get(
            name,
        )

        if isinstance(
            spec,
            dict,
        ) and (
            "default" in spec
        ):
            repaired[name] = spec["default"]

            notes.append(
                f"default {name}",
            )

    return (
        repaired,
        notes,
    )


class GuardedToolRegistry(
    ToolRegistry,
):
    """Same registry surface as ToolRegistry with the guard on execute()."""

    def __init__(
        self,
        supervisor: Any,
        source: ToolRegistry,
    ):
        super().__init__(
            timeout=source.timeout,
            governance=source.governance,
        )

        # Share the source registry's tool/adapter state so discovery,
        # governance and adapters stay exactly the configured ones.
        self._tools = source._tools

        self._adapters = source._adapters

        self.supervisor = supervisor

    # =====================================================
    # Execution boundary
    # =====================================================

    async def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        approved_tools: set[str]
        | frozenset[str]
        | None = None,
    ) -> Any:
        guard_started = perf_counter()

        try:
            return await self._guarded_execute(
                name,
                arguments,
                approved_tools=approved_tools,
            )

        finally:
            self.supervisor._spend_overhead(
                guard_started,
            )

    async def _guarded_execute(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        approved_tools: set[str]
        | frozenset[str]
        | None = None,
    ) -> Any:
        supervisor = self.supervisor

        mode = supervisor.mode

        # -------------------------------------------------
        # Step budget: every guarded action consumes a step.
        # -------------------------------------------------

        if not supervisor.budget.can_step():
            supervisor.terminate(
                reason="STEP_BUDGET_EXHAUSTED",
                diagnosis=diagnose_unknown(
                    {
                        "stage": "tool_guard",
                        "tool": name,
                        "usedSteps": supervisor.budget.used_steps,
                        "maxSteps": supervisor.budget.max_steps,
                    },
                ),
                subject=f"tool call {name}",
            )

        supervisor.budget.consume_step()

        # -------------------------------------------------
        # Governance boundary (existing semantics, unchanged).
        # -------------------------------------------------

        try:
            tool = self.authorize(
                name,
                approved_tools=approved_tools,
            )

        except ToolError as exc:
            supervisor.state_machine.try_transition(
                HarnessRunState.TOOL_GUARD,
            )

            self._record_tool_error(
                name,
                exc,
                tool=None,
            )

            raise

        supervisor.state_machine.try_transition(
            HarnessRunState.TOOL_GUARD,
        )

        arguments = dict(
            arguments,
        )

        risk = _side_effect_risk(
            tool,
        )

        # -------------------------------------------------
        # Deterministic loop detection before the action.
        # -------------------------------------------------

        fingerprint = action_fingerprint(
            action_type="tool_call",
            agent_name=supervisor._current_agent or "unknown",
            tool_name=tool.name,
            arguments=arguments,
            target_object_id=None,
            argument_aliases=tool.argument_aliases,
        )

        marker_before = (
            supervisor.loop_detector._last_progress
        )

        would_repeat = (
            supervisor.loop_detector.would_repeat_without_progress(
                fingerprint,
                marker_before,
            )
        )

        if would_repeat:
            record_fingerprint = fingerprint

            validation = supervisor.loop_detector.validation_result(
                _LoopRecordStub(
                    record_fingerprint,
                    tool.name,
                ),
            )

            supervisor.emit(
                "loop_validation",
                subject=f"tool call {tool.name}",
                validation=validation,
                severity="error",
            )

            if supervisor.blocking:
                diagnosis = diagnose_loop(
                    validation.evidence,
                )

                supervisor.terminate(
                    reason="LOOP_DETECTED",
                    validation=validation,
                    diagnosis=diagnosis,
                    subject=f"tool call {tool.name}",
                )

        # -------------------------------------------------
        # Input validation.
        # -------------------------------------------------

        input_validation = validate_tool_input(
            arguments,
            tool.input_schema,
        )

        supervisor.emit(
            "tool_input_validation",
            subject=f"tool call {tool.name}",
            validation=input_validation,
            severity=(
                "error"
                if input_validation.status == "FAIL"
                else "info"
            ),
        )

        if input_validation.status == "FAIL":
            if mode.value == "OBSERVE":
                # Record only; the underlying registry still raises its own
                # deterministic schema error exactly like the legacy path.
                pass

            elif (
                supervisor.auto_repair
                and input_validation.code
                == "INPUT_MISSING_WITH_DEFAULT"
                and supervisor.budget.can_repair()
            ):
                (
                    repaired,
                    notes,
                ) = apply_argument_repair(
                    arguments,
                    tool,
                )

                recheck = validate_tool_input(
                    repaired,
                    tool.input_schema,
                )

                if recheck.status == "PASS":
                    supervisor.budget.consume_repair()

                    recovery = HarnessRecovery(
                        action="REPAIR_ARGS",
                        reason=(
                            "schema default/argument alias "
                            "deterministically resolved the input"
                        ),
                        tool=tool.name,
                        attempt=supervisor.budget.used_repairs,
                        success=True,
                        detail={
                            "applied": notes,
                        },
                    )

                    supervisor.emit(
                        "recovery",
                        subject=f"tool call {tool.name}",
                        recovery=recovery,
                    )

                    arguments = repaired

                    fingerprint = action_fingerprint(
                        action_type="tool_call",
                        agent_name=supervisor._current_agent or "unknown",
                        tool_name=tool.name,
                        arguments=arguments,
                        target_object_id=None,
                        argument_aliases=tool.argument_aliases,
                    )

            else:
                diagnosis = diagnose_tool_input_failure(
                    input_validation,
                    side_effect_risk=risk,
                )

                supervisor.state_machine.try_transition(
                    HarnessRunState.DIAGNOSING,
                )

                self._block(
                    tool,
                    input_validation,
                    diagnosis,
                )

        # -------------------------------------------------
        # Call the underlying registry (authorize + schema check +
        # adapter + timeout + error normalization are unchanged).
        # -------------------------------------------------

        supervisor.emit(
            "tool_call_started",
            subject=(
                f"tool call {tool.name} "
                f"({tool.protocol}, risk={risk.value})"
            ),
        )

        request_sent = False

        try:
            result = await ToolRegistry.execute(
                self,
                name,
                arguments,
                approved_tools=approved_tools,
            )

            request_sent = True

        except ToolError as exc:
            request_sent = (
                exc.error_type
                in _SENT_OR_UNKNOWN_ERRORS
            )

            self._record_tool_error(
                name,
                exc,
                tool=tool,
                request_sent=request_sent,
            )

            if mode.value == "OBSERVE":
                raise

            recovered = False

            if (
                supervisor.auto_repair
                and _retry_allowed(
                    exc,
                    tool,
                    arguments,
                    risk,
                )
                and supervisor.budget.can_retry_tool(
                    tool.name,
                )
            ):
                supervisor.budget.consume_tool_retry(
                    tool.name,
                )

                recovery = HarnessRecovery(
                    action="RETRY",
                    reason=(
                        f"{exc.error_type.value} on "
                        f"{risk.value} tool within budget"
                    ),
                    tool=tool.name,
                    attempt=supervisor.budget.used_tool_retries,
                    success=False,
                )

                supervisor.emit(
                    "recovery",
                    subject=f"tool call {tool.name}",
                    recovery=recovery,
                )

                try:
                    result = await ToolRegistry.execute(
                        self,
                        name,
                        arguments,
                        approved_tools=approved_tools,
                    )

                    recovery.success = True

                    recovery.detail = {
                        "retried": True,
                    }

                    recovered = True

                except ToolError as retry_exc:
                    self._record_tool_error(
                        name,
                        retry_exc,
                        tool=tool,
                        request_sent=(
                            retry_exc.error_type
                            in _SENT_OR_UNKNOWN_ERRORS
                        ),
                    )

                    if (
                        supervisor.auto_repair
                        and _terminates(
                            retry_exc,
                            risk,
                            request_sent=True,
                        )
                    ):
                        diagnosis = diagnose_tool_error(
                            retry_exc.error_type,
                            request_sent=True,
                            side_effect_risk=risk,
                            evidence={
                                "tool": tool.name,
                                "retried": True,
                            },
                        )

                        supervisor.terminate(
                            reason=(
                                "TOOL_OUTCOME_UNKNOWN"
                                if retry_exc.error_type
                                is ToolErrorType.TIMEOUT
                                else f"TOOL_{retry_exc.error_type.value.upper()}"
                            ),
                            diagnosis=diagnosis,
                            subject=f"tool call {tool.name}",
                        )

                    raise

            elif supervisor.auto_repair and _terminates(
                exc,
                risk,
                request_sent=True,
            ):
                diagnosis = diagnose_tool_error(
                    exc.error_type,
                    request_sent=True,
                    side_effect_risk=risk,
                    evidence={
                        "tool": tool.name,
                    },
                )

                supervisor.terminate(
                    reason=(
                        "TOOL_OUTCOME_UNKNOWN"
                        if exc.error_type
                        is ToolErrorType.TIMEOUT
                        else f"TOOL_{exc.error_type.value.upper()}"
                    ),
                    diagnosis=diagnosis,
                    subject=f"tool call {tool.name}",
                )

            if not recovered:
                # No whitelisted recovery applied (or recovery is out of
                # budget): the original error propagates unchanged.
                raise

        # -------------------------------------------------
        # Output validation.
        # -------------------------------------------------

        output_validation = validate_tool_output(
            result,
            tool.output_schema,
        )

        supervisor.emit(
            "tool_output_validation",
            subject=f"tool call {tool.name}",
            validation=output_validation,
            severity=(
                "error"
                if output_validation.status == "FAIL"
                else "info"
            ),
        )

        if output_validation.status == "FAIL":
            if mode.value == "OBSERVE":
                # Record only; the raw result still reaches the agent.
                return result

            if (
                supervisor.auto_repair
                and tool.fallback_tool_id
                and supervisor.budget.can_repair()
                and tool.fallback_tool_id in self._tools
            ):
                fallback = self._tools[
                    tool.fallback_tool_id
                ]

                fallback_input = validate_tool_input(
                    arguments,
                    fallback.input_schema,
                )

                if fallback_input.status in {
                    "PASS",
                    "NOT_CONFIGURED",
                }:
                    supervisor.budget.consume_repair()

                    recovery = HarnessRecovery(
                        action="FALLBACK",
                        reason=(
                            "explicit fallbackToolId with compatible "
                            "input contract"
                        ),
                        tool=fallback.name,
                        attempt=supervisor.budget.used_repairs,
                        success=False,
                    )

                    supervisor.emit(
                        "recovery",
                        subject=(
                            f"tool call {tool.name} "
                            f"-> {fallback.name}"
                        ),
                        recovery=recovery,
                    )

                    fallback_result = await ToolRegistry.execute(
                        self,
                        fallback.name,
                        arguments,
                        approved_tools=approved_tools,
                    )

                    fallback_validation = validate_tool_output(
                        fallback_result,
                        fallback.output_schema,
                    )

                    supervisor.emit(
                        "tool_output_validation",
                        subject=f"fallback tool call {fallback.name}",
                        validation=fallback_validation,
                        severity=(
                            "error"
                            if fallback_validation.status == "FAIL"
                            else "info"
                        ),
                    )

                    if fallback_validation.status != "FAIL":
                        recovery.success = True

                        self._register_success(
                            fallback,
                            arguments,
                            fallback_result,
                            fallback_validation,
                        )

                        return fallback_result

                diagnosis = diagnose_tool_output_failure(
                    output_validation,
                    side_effect_risk=risk,
                    fallback_available=True,
                )

                supervisor.terminate(
                    reason="OUTPUT_SCHEMA_INVALID",
                    validation=output_validation,
                    diagnosis=diagnosis,
                    subject=f"tool call {tool.name}",
                )

            if (
                supervisor.auto_repair
                and risk is SideEffectRisk.READ_ONLY
                and supervisor.budget.can_retry_tool(
                    tool.name,
                )
            ):
                supervisor.budget.consume_tool_retry(
                    tool.name,
                )

                recovery = HarnessRecovery(
                    action="RETRY",
                    reason=(
                        "output schema violation retried once on a "
                        "read-only tool"
                    ),
                    tool=tool.name,
                    attempt=supervisor.budget.used_tool_retries,
                    success=False,
                )

                supervisor.emit(
                    "recovery",
                    subject=f"tool call {tool.name}",
                    recovery=recovery,
                )

                result = await ToolRegistry.execute(
                    self,
                    name,
                    arguments,
                    approved_tools=approved_tools,
                )

                output_validation = validate_tool_output(
                    result,
                    tool.output_schema,
                )

                supervisor.emit(
                    "tool_output_validation",
                    subject=(
                        f"tool call {tool.name} after retry"
                    ),
                    validation=output_validation,
                    severity=(
                        "error"
                        if output_validation.status == "FAIL"
                        else "info"
                    ),
                )

                if output_validation.status != "FAIL":
                    recovery.success = True

                    self._register_success(
                        tool,
                        arguments,
                        result,
                        output_validation,
                    )

                    return result

            if (
                supervisor.auto_repair
                and tool.fallback_tool_id
            ):
                diagnosis = diagnose_tool_output_failure(
                    output_validation,
                    side_effect_risk=risk,
                    fallback_available=True,
                )

            else:
                diagnosis = diagnose_tool_output_failure(
                    output_validation,
                    side_effect_risk=risk,
                    fallback_available=bool(
                        tool.fallback_tool_id,
                    ),
                )

            supervisor.terminate(
                reason="OUTPUT_SCHEMA_INVALID",
                validation=output_validation,
                diagnosis=diagnosis,
                subject=f"tool call {tool.name}",
            )

        # -------------------------------------------------
        # Success: register fingerprint/progress and return.
        # -------------------------------------------------

        self._register_success(
            tool,
            arguments,
            result,
            output_validation,
        )

        return result

    # =====================================================
    # Helpers
    # =====================================================

    def _register_success(
        self,
        tool: ToolDefinition,
        arguments: dict[str, Any],
        result: Any,
        output_validation: Any,
    ) -> None:
        supervisor = self.supervisor

        risk = _side_effect_risk(
            tool,
        )

        if risk in {
            SideEffectRisk.IDEMPOTENT_WRITE,
            SideEffectRisk.NON_IDEMPOTENT_WRITE,
        }:
            supervisor.note_completed_write_tool(
                tool.name,
            )

        fingerprint = action_fingerprint(
            action_type="tool_call",
            agent_name=supervisor._current_agent or "unknown",
            tool_name=tool.name,
            arguments=arguments,
            target_object_id=None,
            argument_aliases=tool.argument_aliases,
        )

        marker, marker_available = extract_progress_marker(
            result,
        )

        supervisor.loop_detector.register_output(
            fingerprint,
            marker,
        )

        step_validation = validate_step(
            step_status="completed",
            tool_name=tool.name,
            known_tools=set(
                self._tools.keys(),
            ),
        )

        supervisor.emit(
            "step_validation",
            subject=f"tool call {tool.name} completed",
            validation=step_validation,
        )

    def _record_tool_error(
        self,
        name: str,
        exc: ToolError,
        *,
        tool: ToolDefinition | None,
        request_sent: bool = False,
    ) -> None:
        """Record a tool failure without changing its outcome."""

        supervisor = self.supervisor

        risk = (
            _side_effect_risk(
                tool,
            )
            if tool is not None
            else SideEffectRisk.UNKNOWN
        )

        diagnosis = diagnose_tool_error(
            exc.error_type,
            request_sent=request_sent,
            side_effect_risk=risk,
            evidence={
                "tool": name,
                "errorCode": exc.error_type.value,
                "requestSent": request_sent,
            },
        )

        step_validation = validate_step(
            step_status="error",
            tool_name=name,
            known_tools=set(
                self._tools.keys(),
            ),
        )

        supervisor.emit(
            "step_validation",
            subject=f"tool call {name} failed",
            validation=step_validation,
            severity="error",
        )

        supervisor.emit(
            "tool_error",
            subject=f"tool call {name}",
            diagnosis=diagnosis,
            severity="error",
        )

    def _block(
        self,
        tool: ToolDefinition,
        validation: Any,
        diagnosis: Any,
    ) -> None:
        """ENFORCE/AUTO_REPAIR: fail before the adapter is reached."""

        self.supervisor.terminate(
            reason=f"INPUT_VALIDATION_{validation.code}",
            validation=validation,
            diagnosis=diagnosis,
            subject=f"tool call {tool.name}",
        )


class _LoopRecordStub:
    """Minimal shape for LoopDetector.validation_result()."""

    def __init__(
        self,
        fingerprint: str,
        tool_name: str,
    ):
        self.fingerprint = fingerprint

        self.tool_name = tool_name

        self.progress_available = False

        self.progress_marker = None


def _retry_allowed(
    exc: ToolError,
    tool: ToolDefinition,
    arguments: dict[str, Any],
    risk: SideEffectRisk,
) -> bool:
    """RETRY conditions from the recovery policy (P37 §7.7).

    Read-only tools may retry on TIMEOUT/UNAVAILABLE. Idempotent writes may
    retry only when the tool declares idempotency-key support and the
    request actually carried a stable key. Non-idempotent writes and
    unknown-risk tools are never retried after the request was sent.
    """

    if exc.error_type not in {
        ToolErrorType.TIMEOUT,
        ToolErrorType.UNAVAILABLE,
    }:
        return False

    if risk is SideEffectRisk.READ_ONLY:
        return True

    if (
        risk
        is SideEffectRisk.IDEMPOTENT_WRITE
        and tool.supports_idempotency_key
    ):
        return bool(
            arguments.get(
                _IDEMPOTENCY_KEY,
            ),
        )

    return False


def _terminates(
    exc: ToolError,
    risk: SideEffectRisk,
    *,
    request_sent: bool,
) -> bool:
    """AUTO_REPAIR terminates instead of letting the error float when the
    outcome of a sent non-idempotent (or unknown-risk) write is unknown."""

    return (
        request_sent
        and exc.error_type
        is ToolErrorType.TIMEOUT
        and risk
        in {
            SideEffectRisk.NON_IDEMPOTENT_WRITE,
            SideEffectRisk.UNKNOWN,
        }
    )
