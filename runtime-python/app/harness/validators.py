"""Deterministic P0 validators (P37 §7.3).

No semantic similarity, no model scoring, no post-hoc auto-correction. Rules
are decided by JSON Schema, stable error codes and explicit state only. When
a business rule cannot be expressed as schema or an explicit rule, the
validator reports NOT_CONFIGURED instead of guessing a PASS.
"""

import json

from typing import (
    Any,
)

from app.harness.contracts import (
    ValidationResult,
)


# =========================================================
# JSON Schema subset checker
# =========================================================


def _matches_type(
    value: Any,
    expected: str,
) -> bool:
    if expected == "string":
        return isinstance(
            value,
            str,
        )

    if expected == "number":
        return isinstance(
            value,
            (int, float),
        ) and not isinstance(
            value,
            bool,
        )

    if expected == "integer":
        return isinstance(
            value,
            int,
        ) and not isinstance(
            value,
            bool,
        )

    if expected == "boolean":
        return isinstance(
            value,
            bool,
        )

    if expected == "object":
        return isinstance(
            value,
            dict,
        )

    if expected == "array":
        return isinstance(
            value,
            list,
        )

    if expected == "null":
        return value is None

    return True


def _check_value(
    value: Any,
    spec: dict[str, Any],
    path: str,
    errors: list[
        tuple[str, str],
    ],
) -> None:
    """Collect (fieldPath, code) violations for one value."""

    expected = spec.get(
        "type",
    )

    if isinstance(
        expected,
        str,
    ) and not _matches_type(
        value,
        expected,
    ):
        errors.append(
            (
                path,
                "TYPE_MISMATCH",
            ),
        )

        return

    # enum
    enum_values = spec.get(
        "enum",
    )

    if isinstance(
        enum_values,
        list,
    ) and enum_values:
        if not any(
            value == candidate
            for candidate in enum_values
        ):
            errors.append(
                (
                    path,
                    "ENUM_MISMATCH",
                ),
            )

    # numeric range
    if isinstance(
        value,
        (int, float),
    ) and not isinstance(
        value,
        bool,
    ):
        minimum = spec.get(
            "minimum",
        )

        maximum = spec.get(
            "maximum",
        )

        if isinstance(
            minimum,
            (int, float),
        ) and value < minimum:
            errors.append(
                (
                    path,
                    "RANGE_TOO_SMALL",
                ),
            )

        if isinstance(
            maximum,
            (int, float),
        ) and value > maximum:
            errors.append(
                (
                    path,
                    "RANGE_TOO_LARGE",
                ),
            )

    # string length
    if isinstance(
        value,
        str,
    ):
        minimum = spec.get(
            "minLength",
        )

        maximum = spec.get(
            "maxLength",
        )

        if isinstance(
            minimum,
            int,
        ) and len(value) < minimum:
            errors.append(
                (
                    path,
                    "STRING_TOO_SHORT",
                ),
            )

        if isinstance(
            maximum,
            int,
        ) and len(value) > maximum:
            errors.append(
                (
                    path,
                    "STRING_TOO_LONG",
                ),
            )

    # nested object
    if isinstance(
        value,
        dict,
    ):
        properties = spec.get(
            "properties",
        )

        if isinstance(
            properties,
            dict,
        ):
            required = (
                spec.get(
                    "required",
                )
                or []
            )

            for name in required:
                if (
                    isinstance(
                        name,
                        str,
                    )
                    and name
                    not in value
                ):
                    errors.append(
                        (
                            f"{path}.{name}",
                            "REQUIRED_MISSING",
                        ),
                    )

            if (
                spec.get(
                    "additionalProperties",
                )
                is False
            ):
                for key in value:
                    if key not in properties:
                        errors.append(
                            (
                                f"{path}.{key}",
                                "ADDITIONAL_PROPERTY",
                            ),
                        )

            for key, sub_value in value.items():
                sub_spec = properties.get(
                    key,
                )

                if isinstance(
                    sub_spec,
                    dict,
                ):
                    _check_value(
                        sub_value,
                        sub_spec,
                        f"{path}.{key}",
                        errors,
                    )

    # array items
    if isinstance(
        value,
        list,
    ):
        items = spec.get(
            "items",
        )

        if isinstance(
            items,
            dict,
        ):
            for index, element in enumerate(
                value,
            ):
                _check_value(
                    element,
                    items,
                    f"{path}[{index}]",
                    errors,
                )


def validate_against_schema(
    value: Any,
    schema: dict[str, Any] | None,
) -> list[
    tuple[str, str],
]:
    """Validate a value against the supported JSON-schema subset.

    Returns a list of (fieldPath, code) violations. An empty/missing schema
    is treated as "no contract" by the caller (NOT_CONFIGURED), not as PASS.
    """

    if not isinstance(
        schema,
        dict,
    ) or not schema:
        return []

    errors: list[
        tuple[str, str],
    ] = []

    root_type = schema.get(
        "type",
    )

    if isinstance(
        root_type,
        str,
    ) and not _matches_type(
        value,
        root_type,
    ):
        errors.append(
            (
                "$",
                "TYPE_MISMATCH",
            ),
        )

        return errors

    _check_value(
        value,
        schema,
        "$",
        errors,
    )

    return errors


def summarize_violations(
    violations: list[
        tuple[str, str],
    ],
) -> str:
    return "; ".join(
        f"{path}:{code}"
        for path, code in violations
    )


# =========================================================
# Shared validator naming
# =========================================================

PRE_VALIDATOR = "PreValidator.v1"
TOOL_INPUT_VALIDATOR = "ToolInputValidator.v1"
TOOL_OUTPUT_VALIDATOR = "ToolOutputValidator.v1"
STEP_VALIDATOR = "StepValidator.v1"
RESULT_VALIDATOR = "ResultValidator.v1"
LOOP_VALIDATOR = "LoopValidator.v1"


# =========================================================
# PreValidator
# =========================================================


def validate_precheck(
    *,
    task: str,
    harness_mode: str,
    agent_protocols: list[str],
    tool_names: list[str],
) -> ValidationResult:
    """Agent execution pre-check: task non-empty, mode legal, an executor
    exists for the request, and the tool references are resolvable."""

    if not task or not task.strip():
        return ValidationResult(
            validator=PRE_VALIDATOR,
            status="FAIL",
            code="PRE_TASK_EMPTY",
            message="task must not be empty",
        )

    if harness_mode not in {
        "OFF",
        "OBSERVE",
        "ENFORCE",
        "AUTO_REPAIR",
    }:
        return ValidationResult(
            validator=PRE_VALIDATOR,
            status="FAIL",
            code="PRE_MODE_INVALID",
            message=f"unknown harness mode: {harness_mode}",
        )

    if not agent_protocols:
        return ValidationResult(
            validator=PRE_VALIDATOR,
            status="FAIL",
            code="PRE_NO_EXECUTOR",
            message="no agent/executor available for this request",
        )

    return ValidationResult.pass_result(
        PRE_VALIDATOR,
        "PRE_OK",
    )


# =========================================================
# ToolInputValidator
# =========================================================


def validate_tool_input(
    arguments: dict[str, Any],
    schema: dict[str, Any],
) -> ValidationResult:
    """Validate tool arguments before execution.

    Distinguishes repairable missing-required-with-default from the
    unrepairable missing-required case so the diagnosis table can pick the
    right action.
    """

    if not schema:
        return ValidationResult.not_configured(
            TOOL_INPUT_VALIDATOR,
            "tool has no input schema",
        )

    violations = validate_against_schema(
        arguments,
        schema,
    )

    if not violations:
        return ValidationResult.pass_result(
            TOOL_INPUT_VALIDATOR,
            "INPUT_OK",
        )

    properties = (
        schema.get(
            "properties",
        )
        or {}
    )

    field_paths: list[str] = []

    codes: set[str] = set()

    has_missing_with_default = False

    has_missing_without_default = False

    for path, code in violations:
        field_paths.append(
            path,
        )

        codes.add(
            code,
        )

        if code == "REQUIRED_MISSING":
            name = path.split(
                ".",
            )[-1]

            spec = properties.get(
                name,
            )

            if isinstance(
                spec,
                dict,
            ) and (
                "default" in spec
            ):
                has_missing_with_default = True

            else:
                has_missing_without_default = True

    if has_missing_without_default:
        primary = "INPUT_REQUIRED_MISSING"
    elif has_missing_with_default:
        primary = "INPUT_MISSING_WITH_DEFAULT"
    elif codes == {
        "ENUM_MISMATCH",
    }:
        primary = "INPUT_ENUM_INVALID"
    elif codes & {
        "RANGE_TOO_SMALL",
        "RANGE_TOO_LARGE",
    }:
        primary = "INPUT_RANGE_INVALID"
    elif codes == {
        "ADDITIONAL_PROPERTY",
    }:
        primary = "INPUT_UNKNOWN_FIELD"
    else:
        primary = "INPUT_TYPE_INVALID"

    return ValidationResult(
        validator=TOOL_INPUT_VALIDATOR,
        status="FAIL",
        code=primary,
        message=(
            "tool input validation failed: "
            + summarize_violations(
                violations,
            )
        ),
        fieldPaths=field_paths,
        evidence={
            "violations": [
                {
                    "fieldPath": path,
                    "code": code,
                }
                for path, code in violations
            ],
        },
    )


# =========================================================
# ToolOutputValidator
# =========================================================


_UNIFIED_ERROR_KEYS = {
    "error",
    "errorCode",
    "error_code",
}


def validate_tool_output(
    result: Any,
    schema: dict[str, Any] | None,
) -> ValidationResult:
    """Validate a successful tool result.

    Without an outputSchema the status is NOT_CONFIGURED - it must never be
    recorded as PASS. With a schema the result must satisfy it; a result that
    itself carries the unified error structure is a failure as well.
    """

    if not schema:
        return ValidationResult.not_configured(
            TOOL_OUTPUT_VALIDATOR,
            "tool has no outputSchema",
        )

    if isinstance(
        result,
        dict,
    ) and (
        _UNIFIED_ERROR_KEYS
        & set(
            result.keys(),
        )
    ):
        error_payload = result.get(
            "error",
        )

        error_code = (
            result.get(
                "errorCode",
            )
            or result.get(
                "error_code",
            )
            or ""
        )

        summary = (
            str(error_payload)
            if not isinstance(
                error_payload,
                dict,
            )
            else str(
                error_payload.get(
                    "message",
                    "",
                )
            )
        )[:200]

        return ValidationResult(
            validator=TOOL_OUTPUT_VALIDATOR,
            status="FAIL",
            code="TOOL_ERROR_RESULT",
            message=(
                "tool returned a structured error payload: "
                + summary
            ),
            fieldPaths=["$"],
            evidence={
                "errorCode": str(error_code)[:100],
            },
        )

    violations = validate_against_schema(
        result,
        schema,
    )

    if violations:
        return ValidationResult(
            validator=TOOL_OUTPUT_VALIDATOR,
            status="FAIL",
            code="OUTPUT_SCHEMA_INVALID",
            message=(
                "tool output does not satisfy outputSchema: "
                + summarize_violations(
                    violations,
                )
            ),
            fieldPaths=[
                path
                for path, _ in violations
            ],
            evidence={
                "violations": [
                    {
                        "fieldPath": path,
                        "code": code,
                    }
                    for path, code in violations
                ],
            },
        )

    return ValidationResult.pass_result(
        TOOL_OUTPUT_VALIDATOR,
        "OUTPUT_OK",
    )


# =========================================================
# StepValidator
# =========================================================

_STEP_STATUS_VALUES = {
    "running",
    "completed",
    "error",
    "skipped",
}


def validate_step(
    *,
    step_status: str,
    tool_name: str,
    known_tools: set[str],
) -> ValidationResult:
    """Each finished step: status legal, tool reference resolvable."""

    field_paths: list[str] = []

    if (
        step_status
        not in _STEP_STATUS_VALUES
    ):
        field_paths.append(
            "status",
        )

    if (
        tool_name
        and tool_name
        not in known_tools
    ):
        field_paths.append(
            "tool",
        )

    if field_paths:
        return ValidationResult(
            validator=STEP_VALIDATOR,
            status="FAIL",
            code="STEP_INVALID",
            message=(
                "step references are invalid: "
                + ", ".join(
                    field_paths,
                )
            ),
            fieldPaths=field_paths,
        )

    return ValidationResult.pass_result(
        STEP_VALIDATOR,
        "STEP_OK",
    )


# =========================================================
# ResultValidator
# =========================================================


def validate_final_result(
    answer: str,
    result_schema: dict[str, Any] | None,
) -> ValidationResult:
    """Final result validation.

    The explicit P0 business rule is: an empty result is always a failure.
    When a resultSchema is configured, the answer must parse as JSON and
    satisfy the schema. Without one, only the explicit rule applies and the
    schema part is reported as NOT_CONFIGURED in evidence.
    """

    if (
        answer is None
        or not str(answer).strip()
    ):
        return ValidationResult(
            validator=RESULT_VALIDATOR,
            status="FAIL",
            code="RESULT_EMPTY",
            message="final result is empty",
            fieldPaths=["answer"],
        )

    if not result_schema:
        return ValidationResult(
            validator=RESULT_VALIDATOR,
            status="NOT_CONFIGURED",
            code="RESULT_SCHEMA_NOT_CONFIGURED",
            message=(
                "non-empty result passed the explicit rule; "
                "no resultSchema configured"
            ),
            evidence={
                "answerChars": len(answer),
            },
        )

    try:
        parsed = json.loads(
            answer,
        )

    except (
        ValueError,
        TypeError,
    ):
        return ValidationResult(
            validator=RESULT_VALIDATOR,
            status="FAIL",
            code="RESULT_NOT_JSON",
            message=(
                "resultSchema is configured but the answer "
                "is not valid JSON"
            ),
            fieldPaths=["answer"],
        )

    violations = validate_against_schema(
        parsed,
        result_schema,
    )

    if violations:
        return ValidationResult(
            validator=RESULT_VALIDATOR,
            status="FAIL",
            code="RESULT_INCOMPLETE",
            message=(
                "final result does not satisfy resultSchema: "
                + summarize_violations(
                    violations,
                )
            ),
            fieldPaths=[
                path
                for path, _ in violations
            ],
            evidence={
                "violations": [
                    {
                        "fieldPath": path,
                        "code": code,
                    }
                    for path, code in violations
                ],
            },
        )

    return ValidationResult.pass_result(
        RESULT_VALIDATOR,
        "RESULT_OK",
    )
