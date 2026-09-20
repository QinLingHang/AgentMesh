"""Deterministic loop detection (P37 §7.4).

Fingerprint = action type + agent identity + tool identity + canonical
argument hash + target object identity. Progress markers are supplied
explicitly by executor steps (e.g. an artifact version or result cursor); a
tool may opt in by including a "progressMarker" key in its output. Actions
that cannot provide a marker are judged on fingerprint identity only and the
report flags the limited judgment basis.
"""

import hashlib

import json

from dataclasses import (
    dataclass,
)

from typing import Any

from app.harness.contracts import (
    ValidationResult,
)

from app.harness.validators import (
    LOOP_VALIDATOR,
)


# Explicit progress-marker key a tool output may carry.
PROGRESS_MARKER_KEY = "progressMarker"


@dataclass(
    slots=True,
)
class ActionRecord:
    fingerprint: str

    tool_name: str

    arguments: dict[str, Any]

    progress_marker: str | None

    # False when the action could not provide any progress marker.
    progress_available: bool = False


def canonical_arguments(
    arguments: dict[str, Any],
    aliases: dict[str, str] | None = None,
) -> str:
    """Canonical JSON of arguments: alias keys normalized, keys sorted.

    Only explicit argumentAliases are applied - no semantic guessing.
    """

    normalized: dict[str, Any] = {}

    for key, value in (
        arguments
        or {}
    ).items():
        canonical_key = key

        if aliases and key in aliases:
            canonical_key = aliases[key]

        normalized[canonical_key] = value

    return json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )


def action_fingerprint(
    *,
    action_type: str,
    agent_name: str,
    tool_name: str,
    arguments: dict[str, Any],
    target_object_id: str | None,
    argument_aliases: dict[str, str] | None = None,
) -> str:
    payload = "|".join(
        (
            action_type,
            agent_name,
            tool_name,
            target_object_id or "",
            canonical_arguments(
                arguments,
                argument_aliases,
            ),
        ),
    )

    return hashlib.sha256(
        payload.encode(
            "utf-8",
        ),
    ).hexdigest()[:32]


def extract_progress_marker(
    result: Any,
) -> tuple[
    str | None,
    bool,
]:
    """Read the explicit progress marker from a tool output, if any."""

    if isinstance(
        result,
        dict,
    ) and (
        PROGRESS_MARKER_KEY
        in result
    ):
        marker = result[PROGRESS_MARKER_KEY]

        return (
            str(marker),
            True,
        )

    return (
        None,
        False,
    )


class LoopDetector:
    """Tracks consecutive identical no-progress actions.

    The default threshold of 2 means the third identical no-progress action
    is terminated *before* it executes.
    """

    def __init__(
        self,
        threshold: int = 2,
    ):
        self.threshold = max(
            1,
            threshold,
        )

        self._last_fingerprint: str | None = None

        self._last_progress: str | None = None

        self._no_progress_count = 0

    def register_output(
        self,
        fingerprint: str,
        progress_marker: str | None,
    ) -> None:
        """Feed the outcome of an executed action into the detector."""

        if (
            fingerprint
            == self._last_fingerprint
        ) and (
            progress_marker
            == self._last_progress
        ):
            self._no_progress_count += 1

            return

        self._last_fingerprint = fingerprint

        self._last_progress = progress_marker

        self._no_progress_count = 0

    def would_repeat_without_progress(
        self,
        fingerprint: str,
        progress_marker: str | None,
    ) -> bool:
        """Would executing this action repeat the last no-progress one?

        True when the fingerprint is identical to the last action, the
        progress marker has not changed, and the repeat count would reach
        the threshold if the action executed again.
        """

        if fingerprint != self._last_fingerprint:
            return False

        if progress_marker != self._last_progress:
            return False

        return (
            self._no_progress_count
            + 1
            >= self.threshold
        )

    @property
    def no_progress_count(
        self,
    ) -> int:
        return self._no_progress_count

    def judgment_basis(
        self,
        progress_available: bool,
    ) -> str:
        return (
            "fingerprint+progressMarker"
            if progress_available
            else "fingerprint_only"
        )

    def validation_result(
        self,
        record: ActionRecord,
    ) -> ValidationResult:
        return ValidationResult(
            validator=LOOP_VALIDATOR,
            status="FAIL",
            code="LOOP_DETECTED",
            message=(
                "identical action repeated without progress; "
                f"threshold={self.threshold}; "
                f"basis={self.judgment_basis(record.progress_available)}"
            ),
            fieldPaths=["action"],
            evidence={
                "fingerprint": record.fingerprint,
                "tool": record.tool_name,
                "noProgressCount": self._no_progress_count + 1,
                "progressMarker": record.progress_marker,
                "progressMarkerAvailable": record.progress_available,
            },
        )
