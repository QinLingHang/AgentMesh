"""P37 Agent Harness: supervision layer for the Agent execution chain.

Public surface:

    contracts   config/state/validation/diagnosis/event/report contracts
    state       central state machine
    validators  deterministic P0 validators
    loop        deterministic loop detection (fingerprints + progress markers)
    diagnosis   rule-table failure diagnosis
    recovery    bounded replan policy
    guard       Guarded Tool Executor (ToolRegistry wrapper)
    supervisor  run mainline shared by every harness capability
"""

from app.harness.contracts import (
    ALLOWED_TRANSITIONS,
    DiagnosisCategory,
    FailureDiagnosis,
    HarnessBudget,
    HarnessConfig,
    HarnessEvent,
    HarnessMode,
    HarnessOutcome,
    HarnessRecovery,
    HarnessReport,
    HarnessRunState,
    HarnessSummary,
    HarnessTerminatedError,
    InvalidHarnessTransitionError,
    RecommendedAction,
    SideEffectRisk,
    ValidationResult,
    assert_transition,
)
from app.harness.guard import (
    GuardedToolRegistry,
    apply_argument_repair,
)
from app.harness.loop import (
    ActionRecord,
    LoopDetector,
    action_fingerprint,
)
from app.harness.recovery import (
    replan_decision,
    replan_prompt,
)
from app.harness.state import (
    HarnessStateMachine,
)
from app.harness.supervisor import (
    HarnessSupervisor,
    create_harness_supervisor,
    find_harness_termination,
)

__all__ = [
    "ALLOWED_TRANSITIONS",
    "ActionRecord",
    "DiagnosisCategory",
    "FailureDiagnosis",
    "HarnessBudget",
    "HarnessConfig",
    "HarnessEvent",
    "HarnessMode",
    "HarnessOutcome",
    "HarnessRecovery",
    "HarnessReport",
    "HarnessRunState",
    "HarnessStateMachine",
    "HarnessSummary",
    "HarnessSupervisor",
    "HarnessTerminatedError",
    "GuardedToolRegistry",
    "InvalidHarnessTransitionError",
    "LoopDetector",
    "RecommendedAction",
    "SideEffectRisk",
    "ValidationResult",
    "action_fingerprint",
    "apply_argument_repair",
    "assert_transition",
    "create_harness_supervisor",
    "find_harness_termination",
    "replan_decision",
    "replan_prompt",
]
