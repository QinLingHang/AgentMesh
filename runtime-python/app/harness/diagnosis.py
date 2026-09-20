"""Rule-table failure diagnosis (P37 §7.6).

Diagnosis is a deterministic mapping from stable inputs - ValidationResult
codes, ToolErrorCode, request-sent state, tool side-effect risk, budget and
the last action fingerprint - to a FailureDiagnosis. No separate diagnosis
agent, no second source of uncertainty.
"""

from typing import Any

from app.harness.contracts import (
    DiagnosisCategory,
    FailureDiagnosis,
    RecommendedAction,
    SideEffectRisk,
    ValidationResult,
)
from app.tools.contracts import (
    ToolErrorType,
)


def _diagnosis(
    category: DiagnosisCategory,
    root_cause_code: str,
    *,
    retryable: bool,
    side_effect_risk: SideEffectRisk,
    recommended: RecommendedAction,
    evidence: dict[str, Any] | None = None,
) -> FailureDiagnosis:
    return FailureDiagnosis(
        category=category,
        rootCauseCode=root_cause_code,
        evidence=evidence or {},
        retryable=retryable,
        sideEffectRisk=side_effect_risk,
        recommendedAction=recommended,
    )


def diagnose_tool_input_failure(
    validation: ValidationResult,
    *,
    side_effect_risk: SideEffectRisk = SideEffectRisk.UNKNOWN,
) -> FailureDiagnosis:
    """Input validation failed: repair only what the schema can prove."""

    if validation.code == "INPUT_MISSING_WITH_DEFAULT":
        return _diagnosis(
            DiagnosisCategory.INPUT,
            "INPUT_MISSING_WITH_DEFAULT",
            retryable=True,
            side_effect_risk=side_effect_risk,
            recommended=RecommendedAction.REPAIR_ARGS,
            evidence={
                "fieldPaths": validation.field_paths,
                "repairSource": "schema_default",
            },
        )

    if validation.code == "INPUT_REQUIRED_MISSING":
        # Nothing provable to inject: replan (ask the planner again) or stop.
        return _diagnosis(
            DiagnosisCategory.INPUT,
            "INPUT_REQUIRED_MISSING",
            retryable=False,
            side_effect_risk=side_effect_risk,
            recommended=RecommendedAction.REPLAN,
            evidence={
                "fieldPaths": validation.field_paths,
            },
        )

    return _diagnosis(
        DiagnosisCategory.INPUT,
        validation.code or "INPUT_INVALID",
        retryable=False,
        side_effect_risk=side_effect_risk,
        recommended=RecommendedAction.TERMINATE,
        evidence={
            "fieldPaths": validation.field_paths,
        },
    )


def diagnose_tool_error(
    error_type: ToolErrorType,
    *,
    request_sent: bool,
    side_effect_risk: SideEffectRisk,
    fallback_available: bool = False,
    evidence: dict[str, Any] | None = None,
) -> FailureDiagnosis:
    """Tool execution failed: outcome-knownness decides the action.

    A non-idempotent write whose request was already sent but whose outcome
    is unknown (timeout after send) must never be retried automatically.
    """

    payload = dict(evidence or {})

    payload.setdefault(
        "requestSent",
        request_sent,
    )

    if error_type is ToolErrorType.TIMEOUT:
        if side_effect_risk is SideEffectRisk.READ_ONLY:
            return _diagnosis(
                DiagnosisCategory.TIMEOUT,
                "TOOL_TIMEOUT_READ_ONLY",
                retryable=True,
                side_effect_risk=side_effect_risk,
                recommended=RecommendedAction.RETRY,
                evidence=payload,
            )

        if side_effect_risk in {
            SideEffectRisk.NON_IDEMPOTENT_WRITE,
            SideEffectRisk.UNKNOWN,
        } and request_sent:
            return _diagnosis(
                DiagnosisCategory.TIMEOUT,
                "TOOL_OUTCOME_UNKNOWN",
                retryable=False,
                side_effect_risk=side_effect_risk,
                recommended=RecommendedAction.TERMINATE,
                evidence=payload,
            )

        if side_effect_risk is SideEffectRisk.IDEMPOTENT_WRITE:
            return _diagnosis(
                DiagnosisCategory.TIMEOUT,
                "TOOL_TIMEOUT_IDEMPOTENT_WRITE",
                retryable=True,
                side_effect_risk=side_effect_risk,
                recommended=RecommendedAction.RETRY,
                evidence=payload,
            )

    if error_type is ToolErrorType.UNAVAILABLE:
        if side_effect_risk is SideEffectRisk.READ_ONLY:
            return _diagnosis(
                DiagnosisCategory.TOOL,
                "TOOL_UNAVAILABLE_READ_ONLY",
                retryable=True,
                side_effect_risk=side_effect_risk,
                recommended=RecommendedAction.RETRY,
                evidence=payload,
            )

    if error_type in {
        ToolErrorType.PERMISSION_DENIED,
        ToolErrorType.REQUIRES_APPROVAL,
    }:
        return _diagnosis(
            DiagnosisCategory.AUTHORIZATION,
            f"TOOL_{error_type.value.upper()}",
            retryable=False,
            side_effect_risk=side_effect_risk,
            recommended=RecommendedAction.TERMINATE,
            evidence=payload,
        )

    if error_type is ToolErrorType.NOT_FOUND:
        return _diagnosis(
            DiagnosisCategory.TOOL,
            "TOOL_NOT_FOUND",
            retryable=False,
            side_effect_risk=side_effect_risk,
            recommended=RecommendedAction.TERMINATE,
            evidence=payload,
        )

    return _diagnosis(
        DiagnosisCategory.TOOL,
        f"TOOL_{error_type.value.upper()}",
        retryable=False,
        side_effect_risk=side_effect_risk,
        recommended=RecommendedAction.TERMINATE,
        evidence=payload,
    )


def diagnose_tool_output_failure(
    validation: ValidationResult,
    *,
    side_effect_risk: SideEffectRisk,
    fallback_available: bool = False,
) -> FailureDiagnosis:
    """Output schema violation: prefer the explicit fallback, else retry a
    read-only call. Invalid output is never fed back as success."""

    recommended = (
        RecommendedAction.FALLBACK
        if fallback_available
        else (
            RecommendedAction.RETRY
            if side_effect_risk
            is SideEffectRisk.READ_ONLY
            else RecommendedAction.TERMINATE
        )
    )

    return _diagnosis(
        DiagnosisCategory.OUTPUT,
        validation.code or "OUTPUT_SCHEMA_INVALID",
        retryable=(
            recommended
            is RecommendedAction.RETRY
        ),
        side_effect_risk=side_effect_risk,
        recommended=recommended,
        evidence={
            "fieldPaths": validation.field_paths,
            "fallbackAvailable": fallback_available,
        },
    )


def diagnose_result_failure(
    validation: ValidationResult,
) -> FailureDiagnosis:
    """Final/step result incomplete: one bounded replan is allowed."""

    return _diagnosis(
        DiagnosisCategory.RESULT,
        validation.code or "RESULT_INCOMPLETE",
        retryable=True,
        side_effect_risk=SideEffectRisk.READ_ONLY,
        recommended=RecommendedAction.REPLAN,
        evidence={
            "fieldPaths": validation.field_paths,
        },
    )


def diagnose_loop(
    evidence: dict[str, Any] | None = None,
) -> FailureDiagnosis:
    return _diagnosis(
        DiagnosisCategory.LOOP,
        "LOOP_DETECTED",
        retryable=False,
        side_effect_risk=SideEffectRisk.UNKNOWN,
        recommended=RecommendedAction.TERMINATE,
        evidence=dict(evidence or {}),
    )


def diagnose_unknown(
    evidence: dict[str, Any] | None = None,
) -> FailureDiagnosis:
    return _diagnosis(
        DiagnosisCategory.UNKNOWN,
        "UNKNOWN",
        retryable=False,
        side_effect_risk=SideEffectRisk.UNKNOWN,
        recommended=RecommendedAction.TERMINATE,
        evidence=dict(evidence or {}),
    )
