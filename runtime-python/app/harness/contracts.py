"""P37 Agent Harness contracts.

The Harness is a supervision layer that wraps the Agent execution chain. It
never replaces the Agent, model, planner or tool systems; it validates at
deterministic checkpoints, records evidence, diagnoses failures and performs
whitelisted recovery inside a single unified budget.

All JSON facing fields use camelCase aliases so the Go control plane and the
React client can consume the report/summary payloads without translation.
"""

from datetime import (
    datetime,
    timezone,
)

from enum import (
    Enum,
)

from typing import (
    Any,
    Literal,
)

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
)


# =========================================================
# Modes
# =========================================================


class HarnessMode(
    str,
    Enum,
):
    OFF = "OFF"
    OBSERVE = "OBSERVE"
    ENFORCE = "ENFORCE"
    AUTO_REPAIR = "AUTO_REPAIR"


HarnessModeLiteral = Literal[
    "OFF",
    "OBSERVE",
    "ENFORCE",
    "AUTO_REPAIR",
]


# =========================================================
# Tool side-effect risk (ToolDefinition extension, P37 §6.2)
# =========================================================


class SideEffectRisk(
    str,
    Enum,
):
    READ_ONLY = "READ_ONLY"
    IDEMPOTENT_WRITE = "IDEMPOTENT_WRITE"
    NON_IDEMPOTENT_WRITE = "NON_IDEMPOTENT_WRITE"
    # Legacy default for tools registered before the harness contract existed.
    # Unknown risk can never justify an automatic write retry.
    UNKNOWN = "UNKNOWN"


SideEffectRiskLiteral = Literal[
    "READ_ONLY",
    "IDEMPOTENT_WRITE",
    "NON_IDEMPOTENT_WRITE",
    "UNKNOWN",
]


# =========================================================
# Harness run state machine (P37 §6.3)
# =========================================================


class HarnessRunState(
    str,
    Enum,
):
    CREATED = "CREATED"
    PRECHECK = "PRECHECK"
    EXECUTING = "EXECUTING"
    TOOL_GUARD = "TOOL_GUARD"
    STEP_VALIDATING = "STEP_VALIDATING"
    RESULT_VALIDATING = "RESULT_VALIDATING"
    DIAGNOSING = "DIAGNOSING"
    RECOVERING = "RECOVERING"
    COMPLETED = "COMPLETED"
    TERMINATED = "TERMINATED"


HarnessRunStateLiteral = Literal[
    "CREATED",
    "PRECHECK",
    "EXECUTING",
    "TOOL_GUARD",
    "STEP_VALIDATING",
    "RESULT_VALIDATING",
    "DIAGNOSING",
    "RECOVERING",
    "COMPLETED",
    "TERMINATED",
]


ALLOWED_TRANSITIONS: dict[
    HarnessRunState,
    set[HarnessRunState],
] = {
    HarnessRunState.CREATED: {
        HarnessRunState.PRECHECK,
        HarnessRunState.EXECUTING,
        HarnessRunState.TERMINATED,
    },
    HarnessRunState.PRECHECK: {
        HarnessRunState.EXECUTING,
        HarnessRunState.DIAGNOSING,
        HarnessRunState.TERMINATED,
    },
    HarnessRunState.EXECUTING: {
        HarnessRunState.TOOL_GUARD,
        HarnessRunState.STEP_VALIDATING,
        HarnessRunState.RESULT_VALIDATING,
        HarnessRunState.DIAGNOSING,
    },
    HarnessRunState.TOOL_GUARD: {
        HarnessRunState.EXECUTING,
        HarnessRunState.DIAGNOSING,
        HarnessRunState.RECOVERING,
        HarnessRunState.TERMINATED,
    },
    HarnessRunState.STEP_VALIDATING: {
        HarnessRunState.EXECUTING,
        HarnessRunState.DIAGNOSING,
        HarnessRunState.RECOVERING,
        HarnessRunState.TERMINATED,
    },
    HarnessRunState.RESULT_VALIDATING: {
        HarnessRunState.COMPLETED,
        HarnessRunState.DIAGNOSING,
        HarnessRunState.RECOVERING,
        HarnessRunState.TERMINATED,
    },
    HarnessRunState.DIAGNOSING: {
        HarnessRunState.RECOVERING,
        HarnessRunState.TERMINATED,
    },
    HarnessRunState.RECOVERING: {
        HarnessRunState.EXECUTING,
        HarnessRunState.TOOL_GUARD,
        HarnessRunState.RESULT_VALIDATING,
        HarnessRunState.TERMINATED,
    },
    HarnessRunState.COMPLETED: set(),
    HarnessRunState.TERMINATED: set(),
}


class InvalidHarnessTransitionError(
    RuntimeError,
):
    def __init__(
        self,
        current: HarnessRunState,
        target: HarnessRunState,
    ):
        super().__init__(
            (
                f"illegal harness state transition: "
                f"{current.value} -> {target.value}"
            )
        )

        self.current = current
        self.target = target


def assert_transition(
    current: HarnessRunState,
    target: HarnessRunState,
) -> HarnessRunState:
    """Central transition guard: undefined jumps are rejected."""

    allowed = ALLOWED_TRANSITIONS.get(
        current,
        set(),
    )

    if target not in allowed:
        raise InvalidHarnessTransitionError(
            current,
            target,
        )

    return target


# =========================================================
# Validation results (P37 §6.4)
# =========================================================

ValidationStatus = Literal[
    "PASS",
    "FAIL",
    "NOT_CONFIGURED",
]


class ValidationResult(
    BaseModel,
):
    model_config = ConfigDict(
        populate_by_name=True,
    )

    validator: str

    status: ValidationStatus

    code: str = ""

    message: str = ""

    field_paths: list[str] = Field(
        default_factory=list,
        alias="fieldPaths",
    )

    # Evidence is always redacted: field paths, stable error codes and
    # short summaries only. Never tokens, credentials or raw payloads.
    evidence: dict[str, Any] = Field(
        default_factory=dict,
    )

    @classmethod
    def pass_result(
        cls,
        validator: str,
        code: str = "OK",
        message: str = "",
    ) -> "ValidationResult":
        return cls(
            validator=validator,
            status="PASS",
            code=code,
            message=message,
        )

    @classmethod
    def not_configured(
        cls,
        validator: str,
        message: str = "",
    ) -> "ValidationResult":
        return cls(
            validator=validator,
            status="NOT_CONFIGURED",
            code="NOT_CONFIGURED",
            message=message,
        )


# =========================================================
# Failure diagnosis (P37 §6.5 / §7.6)
# =========================================================


class DiagnosisCategory(
    str,
    Enum,
):
    INPUT = "INPUT"
    OUTPUT = "OUTPUT"
    TOOL = "TOOL"
    STEP = "STEP"
    RESULT = "RESULT"
    LOOP = "LOOP"
    TIMEOUT = "TIMEOUT"
    AUTHORIZATION = "AUTHORIZATION"
    UNKNOWN = "UNKNOWN"


class RecommendedAction(
    str,
    Enum,
):
    NONE = "NONE"
    REPAIR_ARGS = "REPAIR_ARGS"
    RETRY = "RETRY"
    FALLBACK = "FALLBACK"
    REPLAN = "REPLAN"
    TERMINATE = "TERMINATE"


class FailureDiagnosis(
    BaseModel,
):
    model_config = ConfigDict(
        populate_by_name=True,
    )

    category: DiagnosisCategory

    root_cause_code: str = Field(
        alias="rootCauseCode",
    )

    evidence: dict[str, Any] = Field(
        default_factory=dict,
    )

    retryable: bool = False

    side_effect_risk: SideEffectRisk = Field(
        default=SideEffectRisk.UNKNOWN,
        alias="sideEffectRisk",
    )

    # Rule-table hits are deterministic; confidence stays EXACT.
    confidence: Literal["EXACT", "HEURISTIC"] = "EXACT"

    recommended_action: RecommendedAction = Field(
        default=RecommendedAction.TERMINATE,
        alias="recommendedAction",
    )


# =========================================================
# Recovery records (P37 §7.7)
# =========================================================


RecoveryActionLiteral = Literal[
    "REPAIR_ARGS",
    "RETRY",
    "FALLBACK",
    "REPLAN",
    "TERMINATE",
]


class HarnessRecovery(
    BaseModel,
):
    model_config = ConfigDict(
        populate_by_name=True,
    )

    action: RecoveryActionLiteral

    reason: str = ""

    tool: str = ""

    attempt: int = 0

    success: bool = False

    detail: dict[str, Any] = Field(
        default_factory=dict,
    )


# =========================================================
# Harness events (P37 §6.6)
# =========================================================


class HarnessEvent(
    BaseModel,
):
    model_config = ConfigDict(
        populate_by_name=True,
    )

    event_id: str = Field(
        alias="eventId",
    )

    # Monotonically increasing inside one run.
    sequence: int

    timestamp: str

    state: str

    type: str

    severity: Literal[
        "info",
        "warning",
        "error",
    ] = "info"

    subject: str = ""

    validation: ValidationResult | None = None

    diagnosis: FailureDiagnosis | None = None

    recovery: HarnessRecovery | None = None

    elapsed_ms: int = Field(
        default=0,
        alias="elapsedMs",
    )


# =========================================================
# Budget (P37 §4.1 / §7.7)
# =========================================================


class HarnessBudgetSnapshot(
    BaseModel,
):
    model_config = ConfigDict(
        populate_by_name=True,
    )

    max_steps: int = Field(
        alias="maxSteps",
    )

    max_repairs: int = Field(
        alias="maxRepairs",
    )

    max_retries_per_tool: int = Field(
        alias="maxRetriesPerTool",
    )

    max_reschedules: int = Field(
        alias="maxReschedules",
    )

    loop_repeat_threshold: int = Field(
        alias="loopRepeatThreshold",
    )

    used_steps: int = 0

    used_repairs: int = 0

    used_tool_retries: int = 0

    used_reschedules: int = 0


class HarnessBudget:
    """Single unified budget for retries, reschedules and repairs.

    Legacy tool retries (ToolLoopRunner) and agent reschedules are observed
    and counted here as well, so one action can only ever be triggered by one
    policy and the totals stay explainable.
    """

    def __init__(
        self,
        *,
        max_steps: int = 12,
        max_repairs: int = 2,
        max_retries_per_tool: int = 1,
        max_reschedules: int = 1,
        loop_repeat_threshold: int = 2,
    ):
        self.max_steps = max_steps
        self.max_repairs = max_repairs
        self.max_retries_per_tool = max_retries_per_tool
        self.max_reschedules = max_reschedules
        self.loop_repeat_threshold = loop_repeat_threshold

        self.used_steps = 0
        self.used_repairs = 0
        self.used_tool_retries = 0
        self.used_reschedules = 0

        # Per-tool retry counters: tool name -> attempts used.
        self._tool_retries: dict[
            str,
            int,
        ] = {}

        # Retries already spent by the legacy ToolLoopRunner for a tool.
        self._inner_tool_retries: dict[
            str,
            int,
        ] = {}

    # -------------------------------------------------
    # Steps
    # -------------------------------------------------

    def can_step(
        self,
    ) -> bool:
        return (
            self.used_steps
            < self.max_steps
        )

    def consume_step(
        self,
    ) -> None:
        self.used_steps += 1

    # -------------------------------------------------
    # Repairs (harness-initiated)
    # -------------------------------------------------

    def can_repair(
        self,
    ) -> bool:
        return (
            self.used_repairs
            < self.max_repairs
        )

    def consume_repair(
        self,
    ) -> None:
        self.used_repairs += 1

    # -------------------------------------------------
    # Tool retries (unified with legacy loop retries)
    # -------------------------------------------------

    def can_retry_tool(
        self,
        tool_name: str,
    ) -> bool:
        if (
            self._inner_tool_retries.get(
                tool_name,
                0,
            )
            > 0
        ):
            # The legacy tool loop already spent the retry for this tool;
            # the harness must not repeat the same action.
            return False

        return (
            self._tool_retries.get(
                tool_name,
                0,
            )
            < self.max_retries_per_tool
        )

    def consume_tool_retry(
        self,
        tool_name: str,
    ) -> None:
        self.used_tool_retries += 1
        self._tool_retries[tool_name] = (
            self._tool_retries.get(
                tool_name,
                0,
            )
            + 1
        )

    def record_inner_tool_retry(
        self,
        tool_name: str,
    ) -> None:
        """Count a retry performed by the legacy ToolLoopRunner itself."""

        self.used_tool_retries += 1
        self._inner_tool_retries[tool_name] = (
            self._inner_tool_retries.get(
                tool_name,
                0,
            )
            + 1
        )

    # -------------------------------------------------
    # Reschedules (legacy agent replacement)
    # -------------------------------------------------

    def can_reschedule(
        self,
    ) -> bool:
        return (
            self.used_reschedules
            < self.max_reschedules
        )

    def consume_reschedule(
        self,
    ) -> None:
        self.used_reschedules += 1

    def snapshot(
        self,
    ) -> HarnessBudgetSnapshot:
        return HarnessBudgetSnapshot(
            maxSteps=self.max_steps,
            maxRepairs=self.max_repairs,
            maxRetriesPerTool=self.max_retries_per_tool,
            maxReschedules=self.max_reschedules,
            loopRepeatThreshold=self.loop_repeat_threshold,
            used_steps=self.used_steps,
            used_repairs=self.used_repairs,
            used_tool_retries=self.used_tool_retries,
            used_reschedules=self.used_reschedules,
        )


# =========================================================
# Config (P37 §6.1)
# =========================================================


class HarnessConfig(
    BaseModel,
):
    """Immutable per-run harness configuration snapshot.

    The snapshot is frozen when the task is created; queueing, restart,
    resume and replay all reuse the same values.
    """

    model_config = ConfigDict(
        populate_by_name=True,
    )

    mode: HarnessModeLiteral = "OFF"

    max_steps: int = Field(
        default=12,
        alias="maxSteps",
        gt=0,
    )

    max_repairs: int = Field(
        default=2,
        alias="maxRepairs",
        ge=0,
    )

    max_retries_per_tool: int = Field(
        default=1,
        alias="maxRetriesPerTool",
        ge=0,
    )

    max_reschedules: int = Field(
        default=1,
        alias="maxReschedules",
        ge=0,
    )

    loop_repeat_threshold: int = Field(
        default=2,
        alias="loopRepeatThreshold",
        ge=1,
    )

    # Optional JSON Schema for the final result. When empty only the
    # configured explicit business rules (e.g. non-empty result) run.
    result_schema: dict[str, Any] | None = Field(
        default=None,
        alias="resultSchema",
    )

    policy_version: str = Field(
        default="p37-v1.0",
        alias="policyVersion",
    )

    @property
    def mode_enum(
        self,
    ) -> HarnessMode:
        return HarnessMode(
            self.mode
        )

    def snapshot_dict(
        self,
    ) -> dict[str, Any]:
        return self.model_dump(
            by_alias=True,
        )


# =========================================================
# Summary / Report (P37 §6.6)
# =========================================================


HarnessOutcome = Literal[
    "COMPLETED",
    "TERMINATED",
    "OBSERVED_ISSUES",
]


class StateTimelineEntry(
    BaseModel,
):
    model_config = ConfigDict(
        populate_by_name=True,
    )

    state: str

    elapsed_ms: int = Field(
        alias="elapsedMs",
    )

    timestamp: str


class HarnessSummary(
    BaseModel,
):
    model_config = ConfigDict(
        populate_by_name=True,
    )

    mode: str

    outcome: HarnessOutcome = "COMPLETED"

    validation_failures: int = Field(
        default=0,
        alias="validationFailures",
    )

    repairs: int = 0

    retries: int = 0

    reschedules: int = 0

    termination_reason: str = Field(
        default="",
        alias="terminationReason",
    )

    overhead_ms: int = Field(
        default=0,
        alias="overheadMs",
    )


class HarnessMetrics(
    BaseModel,
):
    model_config = ConfigDict(
        populate_by_name=True,
    )

    validation_total: int = Field(
        default=0,
        alias="validationTotal",
    )

    validation_failures: int = Field(
        default=0,
        alias="validationFailures",
    )

    validations_not_configured: int = Field(
        default=0,
        alias="validationsNotConfigured",
    )

    diagnoses: int = 0

    recoveries: int = 0

    loop_detections: int = Field(
        default=0,
        alias="loopDetections",
    )

    budget: HarnessBudgetSnapshot | None = None


class HarnessReport(
    BaseModel,
):
    model_config = ConfigDict(
        populate_by_name=True,
    )

    config_snapshot: dict[str, Any] = Field(
        alias="configSnapshot",
    )

    state_timeline: list[StateTimelineEntry] = Field(
        default_factory=list,
        alias="stateTimeline",
    )

    events: list[HarnessEvent] = Field(
        default_factory=list,
    )

    diagnoses: list[FailureDiagnosis] = Field(
        default_factory=list,
    )

    recoveries: list[HarnessRecovery] = Field(
        default_factory=list,
    )

    final_validation: ValidationResult | None = Field(
        default=None,
        alias="finalValidation",
    )

    metrics: HarnessMetrics = Field(
        default_factory=HarnessMetrics,
    )


# =========================================================
# Termination exception
# =========================================================


class HarnessTerminatedError(
    RuntimeError,
):
    """Raised when the harness terminates a run (ENFORCE/AUTO_REPAIR).

    Carries the structured diagnosis plus the supervisor snapshot so the
    runtime boundary can return a FAILED response that still contains the
    complete harness report instead of an opaque 500.
    """

    def __init__(
        self,
        message: str,
        *,
        diagnosis: FailureDiagnosis | None = None,
        validation: ValidationResult | None = None,
        summary: HarnessSummary | None = None,
        report: HarnessReport | None = None,
    ):
        super().__init__(
            message,
        )

        self.diagnosis = diagnosis
        self.validation = validation
        self.summary = summary
        self.report = report


def utc_now_iso(
) -> str:
    return (
        datetime.now(
            timezone.utc,
        )
        .isoformat()
    )
