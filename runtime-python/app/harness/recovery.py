"""Recovery policy for assignment-level replan (P37 §7.7).

Tool-level recovery (REPAIR_ARGS / RETRY / FALLBACK) is implemented inside
the Guarded Tool Executor. This module owns the remaining whitelisted
action - one bounded REPLAN of the original executor with the diagnosis
evidence passed back - plus its allow/deny decision.

Forbidden everywhere: guessing business values,临时搜索替代工具, unbounded
replanning, and replaying a completed side-effect step.
"""

from typing import (
    Any,
)

from app.harness.contracts import (
    HarnessRecovery,
    HarnessTerminatedError,
    ValidationResult,
)


REPLAN_PROTOCOLS = {
    "internal",
    "langgraph",
    # OpenJiuwen agents execute on the internal machinery, so a bounded
    # replan re-invokes them in-process exactly like internal agents.
    "openjiuwen",
}


def replan_decision(
    *,
    validation: ValidationResult,
    protocol: str,
    can_repair: bool,
    replay_safe: bool,
) -> tuple[bool, str]:
    """Decide whether one bounded replan may run for a failed result.

    Returns (allowed, reason). Denials are deterministic and explainable.
    """

    if validation.status != "FAIL":
        return (
            False,
            "result validation did not fail",
        )

    if not can_repair:
        return (
            False,
            "repair budget exhausted",
        )

    if not replay_safe:
        return (
            False,
            (
                "attempt already completed side-effect tool calls; "
                "completed steps are never auto-replayed"
            ),
        )

    if protocol.strip().lower() not in REPLAN_PROTOCOLS:
        return (
            False,
            (
                f"protocol {protocol} cannot be safely re-invoked; "
                "only internal/langgraph executors support bounded replan"
            ),
        )

    return (
        True,
        (
            "one bounded replan within budget with diagnosis evidence "
            "passed back to the original executor"
        ),
    )


def replan_prompt(
    original_task: str,
    previous_result: str,
    validation: ValidationResult,
) -> str:
    """Build the evidence-carrying re-execution input for the same agent."""

    evidence_lines = [
        f"- {path}: {code}"
        for path, code in (
            (
                item.get(
                    "fieldPath",
                    "",
                ),
                item.get(
                    "code",
                    "",
                ),
            )
            for item in validation.evidence.get(
                "violations",
                [],
            )
        )
    ]

    if validation.field_paths and not evidence_lines:
        evidence_lines = [
            f"- {path}"
            for path in validation.field_paths
        ]

    return (
        "The previous result for this subtask failed the deterministic "
        f"result validation ({validation.code}).\n"
        "Produce the complete result. Requirements:\n"
        "1. Address exactly the validation findings below; do not change "
        "anything else about the task.\n"
        "2. Never invent missing tool outputs; re-derive them from the "
        "task context.\n"
        f"Validation findings:\n"
        + (
            "\n".join(
                evidence_lines,
            )
            or f"- {validation.message}"
        )
        + "\n\nOriginal subtask:\n"
        + original_task
        + "\n\nPrevious (incomplete) result:\n"
        + previous_result[:4000]
    )


def raise_unrepairable(
    *,
    validation: ValidationResult,
    reason: str,
    summary: Any = None,
    report: Any = None,
) -> None:
    raise HarnessTerminatedError(
        f"harness terminated run: RESULT_VALIDATION_{validation.code}",
        validation=validation,
        summary=summary,
        report=report,
    )
