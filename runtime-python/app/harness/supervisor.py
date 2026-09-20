"""Harness supervisor: the shared run mainline for all harness capabilities.

Owns the run state machine, the event sequence, the unified budget and the
mode branches. OFF never constructs a supervisor, so the legacy execution
semantics stay byte-for-byte unchanged.
"""

import json

from time import (
    perf_counter,
)

from typing import (
    Any,
    Callable,
    NoReturn,
)

from app.harness.contracts import (
    FailureDiagnosis,
    HarnessConfig,
    HarnessEvent,
    HarnessMetrics,
    HarnessMode,
    HarnessOutcome,
    HarnessRecovery,
    HarnessReport,
    HarnessRunState,
    HarnessSummary,
    HarnessTerminatedError,
    HarnessBudget,
    RecommendedAction,
    ValidationResult,
    utc_now_iso,
)
from app.harness.diagnosis import (
    diagnose_unknown,
)
from app.harness.guard import (
    GuardedToolRegistry,
)
from app.harness.loop import (
    LoopDetector,
)
from app.harness.state import (
    HarnessStateMachine,
)
from app.harness.validators import (
    PRE_VALIDATOR,
    RESULT_VALIDATOR,
    validate_final_result,
    validate_precheck,
)


TraceBridge = Callable[
    [str, str, str, str],
    None,
]


class HarnessSupervisor:
    def __init__(
        self,
        config: HarnessConfig,
        *,
        request_id: str,
        started_perf: float | None = None,
    ):
        self.config = config

        self.request_id = request_id

        self.mode = config.mode_enum

        self._started = (
            started_perf
            if started_perf is not None
            else perf_counter()
        )

        self.state_machine = HarnessStateMachine(
            self._started,
        )

        self.budget = HarnessBudget(
            max_steps=config.max_steps,
            max_repairs=config.max_repairs,
            max_retries_per_tool=config.max_retries_per_tool,
            max_reschedules=config.max_reschedules,
            loop_repeat_threshold=config.loop_repeat_threshold,
        )

        self.loop_detector = LoopDetector(
            config.loop_repeat_threshold,
        )

        self.events: list[
            HarnessEvent,
        ] = []

        self.diagnoses: list[
            FailureDiagnosis,
        ] = []

        self.recoveries: list[
            HarnessRecovery,
        ] = []

        self._sequence = 0

        self._overhead_ms = 0

        self._termination_reason = ""

        self._validation_total = 0

        self._validation_failures = 0

        self._validations_not_configured = 0

        self._final_validation: (
            ValidationResult | None
        ) = None

        self._trace_bridge: TraceBridge | None = None

        self._current_agent = ""

        # Side-effect bookkeeping for the current agent attempt. A completed
        # write-tool call forbids agent-level replan replay for this attempt.
        self._attempt_completed_write_tools: set[
            str,
        ] = set()

    # =====================================================
    # Properties
    # =====================================================

    @property
    def active(
        self,
    ) -> bool:
        return self.mode is not HarnessMode.OFF

    @property
    def blocking(
        self,
    ) -> bool:
        """ENFORCE and AUTO_REPAIR block defined failures."""

        return self.mode in {
            HarnessMode.ENFORCE,
            HarnessMode.AUTO_REPAIR,
        }

    @property
    def auto_repair(
        self,
    ) -> bool:
        return (
            self.mode
            is HarnessMode.AUTO_REPAIR
        )

    # =====================================================
    # Trace bridge + events
    # =====================================================

    def set_trace_bridge(
        self,
        bridge: TraceBridge | None,
    ) -> None:
        self._trace_bridge = bridge

    def elapsed_ms(
        self,
    ) -> int:
        return int(
            (
                perf_counter()
                - self._started
            )
            * 1000
        )

    def _spend_overhead(
        self,
        started: float,
    ) -> None:
        self._overhead_ms += int(
            (
                perf_counter()
                - started
            )
            * 1000
        )

    def emit(
        self,
        type: str,
        *,
        severity: str = "info",
        subject: str = "",
        validation: ValidationResult | None = None,
        diagnosis: FailureDiagnosis | None = None,
        recovery: HarnessRecovery | None = None,
    ) -> HarnessEvent:
        self._sequence += 1

        event = HarnessEvent(
            eventId=f"{self.request_id}-h{self._sequence}",
            sequence=self._sequence,
            timestamp=utc_now_iso(),
            state=self.state_machine.state.value,
            type=type,
            severity=severity,
            subject=subject,
            validation=validation,
            diagnosis=diagnosis,
            recovery=recovery,
            elapsedMs=self.elapsed_ms(),
        )

        self.events.append(
            event,
        )

        if validation is not None:
            self._count_validation(
                validation,
            )

        if diagnosis is not None:
            self.diagnoses.append(
                diagnosis,
            )

        if recovery is not None:
            self.recoveries.append(
                recovery,
            )

        if self._trace_bridge is not None:
            try:
                detail = {
                    "state": event.state,
                    "type": event.type,
                    "subject": event.subject,
                }

                if validation is not None:
                    detail["validation"] = validation.model_dump(
                        by_alias=True,
                    )

                if diagnosis is not None:
                    detail["diagnosis"] = diagnosis.model_dump(
                        by_alias=True,
                    )

                if recovery is not None:
                    detail["recovery"] = recovery.model_dump(
                        by_alias=True,
                    )

                self._trace_bridge(
                    "harness",
                    f"Harness {type}",
                    (
                        "error"
                        if severity == "error"
                        else (
                            "running"
                            if severity == "warning"
                            else "completed"
                        )
                    ),
                    json.dumps(
                        detail,
                        ensure_ascii=False,
                        default=str,
                    ),
                )

            except Exception:
                # Trace bridging must never break supervision itself.
                pass

        return event

    def _count_validation(
        self,
        validation: ValidationResult,
    ) -> None:
        self._validation_total += 1

        if validation.status == "FAIL":
            self._validation_failures += 1

        elif (
            validation.status
            == "NOT_CONFIGURED"
        ):
            self._validations_not_configured += 1

    # =====================================================
    # Precheck
    # =====================================================

    def precheck(
        self,
        *,
        task: str,
        agent_protocols: list[str],
        tool_names: list[str],
    ) -> ValidationResult:
        started = perf_counter()

        self.state_machine.transition(
            HarnessRunState.PRECHECK,
        )

        validation = validate_precheck(
            task=task,
            harness_mode=self.config.mode,
            agent_protocols=agent_protocols,
            tool_names=tool_names,
        )

        self.emit(
            "precheck",
            subject="Agent execution pre-check",
            validation=validation,
            severity=(
                "error"
                if validation.status == "FAIL"
                else "info"
            ),
        )

        self._spend_overhead(
            started,
        )

        if validation.status == "FAIL" and self.blocking:
            self.terminate(
                reason=f"PRECHECK_{validation.code}",
                validation=validation,
                diagnosis=diagnose_unknown(
                    {
                        "stage": "precheck",
                    },
                ),
            )

        self.state_machine.transition(
            HarnessRunState.EXECUTING,
        )

        return validation

    # =====================================================
    # Agent attempt lifecycle
    # =====================================================

    def begin_agent_attempt(
        self,
        agent_name: str,
    ) -> None:
        """Count one step and enforce the step budget before execution."""

        self._attempt_completed_write_tools.clear()

        self._current_agent = agent_name

        if not self.budget.can_step():
            self.terminate(
                reason="STEP_BUDGET_EXHAUSTED",
                diagnosis=diagnose_unknown(
                    {
                        "stage": "agent_attempt",
                        "usedSteps": self.budget.used_steps,
                        "maxSteps": self.budget.max_steps,
                    },
                ),
            )

        self.budget.consume_step()

        self.state_machine.try_transition(
            HarnessRunState.EXECUTING,
        )

    def end_agent_attempt(
        self,
    ) -> None:
        self._current_agent = ""

    def observe_reschedule(
        self,
        *,
        agent: str = "",
        capability: str = "",
    ) -> None:
        """Legacy agent reschedules count into the unified budget."""

        self.budget.consume_reschedule()

        self.emit(
            "reschedule_observed",
            subject=(
                f"agent reschedule counted into harness budget: "
                f"{agent or 'unknown'}/{capability or 'unknown'}"
            ),
            severity="warning",
        )

    def observe_tool_event(
        self,
        payload: dict[str, Any],
    ) -> None:
        """Count legacy ToolLoopRunner retries into the unified budget."""

        title = str(
            payload.get(
                "title",
                "",
            ),
        )

        if title != "Tool Retry":
            return

        tool = str(
            payload.get(
                "tool",
                "",
            ),
        )

        self.budget.record_inner_tool_retry(
            tool,
        )

        self.emit(
            "tool_retry_observed",
            subject=(
                "legacy tool retry counted into "
                f"harness budget: {tool}"
            ),
            severity="warning",
        )

    # =====================================================
    # Termination
    # =====================================================

    def terminate(
        self,
        *,
        reason: str,
        diagnosis: FailureDiagnosis | None = None,
        validation: ValidationResult | None = None,
        subject: str = "",
    ) -> NoReturn:
        self.state_machine.try_transition(
            HarnessRunState.DIAGNOSING,
        )

        if diagnosis is not None:
            self.emit(
                "diagnosis",
                subject=subject or reason,
                diagnosis=diagnosis,
                severity="error",
            )

        self.state_machine.transition(
            HarnessRunState.TERMINATED,
        )

        self._termination_reason = reason

        self.emit(
            "terminated",
            subject=reason,
            severity="error",
        )

        raise HarnessTerminatedError(
            f"harness terminated run: {reason}",
            diagnosis=diagnosis,
            validation=validation,
            summary=self.build_summary(
                "TERMINATED",
            ),
            report=self.build_report(),
        )

    # =====================================================
    # Result validation
    # =====================================================

    def check_result(
        self,
        answer: str,
        *,
        stage: str,
    ) -> ValidationResult:
        """Validate a candidate result (node result or final answer).

        OBSERVE records only; ENFORCE terminates on FAIL; AUTO_REPAIR
        returns the failing validation so the caller can run the bounded
        replan allowed by the recovery policy.
        """

        started = perf_counter()

        self.state_machine.try_transition(
            HarnessRunState.RESULT_VALIDATING,
        )

        validation = validate_final_result(
            answer,
            self.config.result_schema,
        )

        self.emit(
            "result_validation",
            subject=stage,
            validation=validation,
            severity=(
                "error"
                if validation.status == "FAIL"
                else "info"
            ),
        )

        self._spend_overhead(
            started,
        )

        if validation.status != "FAIL":
            self.state_machine.try_transition(
                HarnessRunState.EXECUTING,
            )

            return validation

        if self.mode is HarnessMode.OBSERVE:
            # OBSERVE must not change the outcome: record and move on.
            self.state_machine.try_transition(
                HarnessRunState.EXECUTING,
            )

            return validation

        if (
            self.mode
            is HarnessMode.ENFORCE
        ):
            from app.harness.diagnosis import (
                diagnose_result_failure,
            )

            self.terminate(
                reason=(
                    f"RESULT_VALIDATION_{validation.code}"
                ),
                validation=validation,
                diagnosis=diagnose_result_failure(
                    validation,
                ),
                subject=stage,
            )

        # AUTO_REPAIR: caller decides on the bounded replan.
        self.state_machine.try_transition(
            HarnessRunState.DIAGNOSING,
        )

        return validation

    def after_result_repair_attempt(
        self,
        answer: str,
        *,
        stage: str,
    ) -> None:
        """Re-validate after a bounded replan; FAIL terminates."""

        validation = self.check_result(
            answer,
            stage=(
                f"{stage} after repair"
            ),
        )

        if validation.status == "FAIL":
            from app.harness.diagnosis import (
                diagnose_result_failure,
            )

            self.terminate(
                reason=(
                    f"RESULT_VALIDATION_{validation.code}_AFTER_REPAIR"
                ),
                validation=validation,
                diagnosis=diagnose_result_failure(
                    validation,
                ),
                subject=stage,
            )

        self.state_machine.try_transition(
            HarnessRunState.EXECUTING,
        )

    # =====================================================
    # Tool guard
    # =====================================================

    def guarded_registry(
        self,
        registry: Any,
    ) -> "GuardedToolRegistry":
        return GuardedToolRegistry(
            self,
            registry,
        )

    def note_completed_write_tool(
        self,
        tool_name: str,
    ) -> None:
        self._attempt_completed_write_tools.add(
            tool_name,
        )

    def replan_allowed_for_attempt(
        self,
    ) -> bool:
        """A completed side-effect step must never be auto-replayed."""

        return (
            not self._attempt_completed_write_tools
        )

    # =====================================================
    # Finish / reporting
    # =====================================================

    def build_summary(
        self,
        outcome: HarnessOutcome,
    ) -> HarnessSummary:
        return HarnessSummary(
            mode=self.config.mode,
            outcome=outcome,
            validationFailures=self._validation_failures,
            repairs=self.budget.used_repairs,
            retries=self.budget.used_tool_retries,
            reschedules=self.budget.used_reschedules,
            terminationReason=self._termination_reason,
            overheadMs=self._overhead_ms,
        )

    def build_report(
        self,
    ) -> HarnessReport:
        metrics = HarnessMetrics(
            validationTotal=self._validation_total,
            validationFailures=self._validation_failures,
            validationsNotConfigured=self._validations_not_configured,
            diagnoses=len(self.diagnoses),
            recoveries=len(self.recoveries),
            loopDetections=sum(
                1
                for diagnosis in self.diagnoses
                if diagnosis.root_cause_code
                == "LOOP_DETECTED"
            ),
            budget=self.budget.snapshot(),
        )

        return HarnessReport(
            configSnapshot=self.config.snapshot_dict(),
            stateTimeline=self.state_machine.timeline(),
            events=list(self.events),
            diagnoses=list(self.diagnoses),
            recoveries=list(self.recoveries),
            finalValidation=self._final_validation,
            metrics=metrics,
        )

    def finish(
        self,
        *,
        business_completed: bool,
    ) -> tuple[
        HarnessSummary,
        HarnessReport,
    ]:
        """Close the run and produce the persisted summary/report."""

        if (
            self.state_machine.state
            is HarnessRunState.TERMINATED
        ):
            outcome: HarnessOutcome = "TERMINATED"

        elif (
            business_completed
            and self._validation_failures > 0
            and not self.blocking
        ):
            # Success with observed-only issues.
            outcome = "OBSERVED_ISSUES"

        elif business_completed:
            outcome = "COMPLETED"

            self.state_machine.try_transition(
                HarnessRunState.COMPLETED,
            )

        else:
            outcome = "TERMINATED"

            self._termination_reason = (
                self._termination_reason
                or "RUN_FAILED"
            )

        return (
            self.build_summary(
                outcome,
            ),
            self.build_report(),
        )

    def record_final_validation(
        self,
        validation: ValidationResult,
    ) -> None:
        self._final_validation = validation


# =========================================================
# Module-level helpers
# =========================================================


def find_harness_termination(
    exc: BaseException,
) -> HarnessTerminatedError | None:
    """Walk an exception chain and find a HarnessTerminatedError.

    DAGExecutor wraps node exceptions into DAGExecutionError with the
    original as __cause__, so the structured harness termination must be
    re-identified from the chain - the same pattern as
    find_runtime_interruption.
    """

    current: BaseException | None = exc

    visited: set[int] = set()

    while current is not None:

        current_id = id(
            current,
        )

        if current_id in visited:
            break

        visited.add(
            current_id,
        )

        if isinstance(
            current,
            HarnessTerminatedError,
        ):
            return current

        if current.__cause__ is not None:
            current = current.__cause__

        else:
            current = current.__context__

    return None


def create_harness_supervisor(
    req: Any,
    *,
    started_perf: float | None = None,
) -> HarnessSupervisor | None:
    """Resolve the effective harness configuration for a request.

    OFF - explicit, system default, feature-switch disabled, or simply
    absent - returns None so the existing execution semantics stay
    untouched. The configuration is an immutable per-run snapshot: callers
    must reuse it unchanged across queueing, resume and replay.
    """

    from app.config import (
        settings,
    )

    if not settings.harness_enabled:
        return None

    config = req.harness_config

    if config is None:
        default_mode = (
            settings.harness_default_mode.strip().upper()
            or "OFF"
        )

        if default_mode == "OFF":
            return None

        if default_mode not in {
            "OBSERVE",
            "ENFORCE",
            "AUTO_REPAIR",
        }:
            return None

        config = HarnessConfig(
            mode=default_mode,
            maxSteps=settings.harness_max_steps,
            maxRepairs=settings.harness_max_repairs,
            maxRetriesPerTool=settings.harness_max_retries_per_tool,
            maxReschedules=settings.harness_max_reschedules,
            loopRepeatThreshold=settings.harness_loop_repeat_threshold,
            policyVersion=settings.harness_policy_version,
        )

    elif config.mode_enum is HarnessMode.OFF:
        return None

    return HarnessSupervisor(
        config.model_copy(),
        request_id=req.request_id,
        started_perf=started_perf,
    )
