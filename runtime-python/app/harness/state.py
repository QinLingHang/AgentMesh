"""Harness run state machine with a central transition function."""

from app.harness.contracts import (
    HarnessRunState,
    InvalidHarnessTransitionError,
    StateTimelineEntry,
    assert_transition,
    utc_now_iso,
)


class HarnessStateMachine:
    """All state changes must pass through this class.

    Undefined cross-state jumps are rejected with
    InvalidHarnessTransitionError, which keeps the state timeline a faithful
    record of what actually happened.
    """

    def __init__(
        self,
        started_perf: float,
    ):
        import time

        self._started = started_perf

        self._state = (
            HarnessRunState.CREATED
        )

        self._timeline: list[
            StateTimelineEntry
        ] = [
            StateTimelineEntry(
                state=HarnessRunState.CREATED.value,
                elapsedMs=0,
                timestamp=utc_now_iso(),
            )
        ]

    # -------------------------------------------------
    # Current state
    # -------------------------------------------------

    @property
    def state(
        self,
    ) -> HarnessRunState:
        return self._state

    def elapsed_ms(
        self,
    ) -> int:
        import time

        return int(
            (
                time.perf_counter()
                - self._started
            )
            * 1000
        )

    # -------------------------------------------------
    # Transitions
    # -------------------------------------------------

    def transition(
        self,
        target: HarnessRunState,
    ) -> HarnessRunState:
        if target is self._state:
            return self._state

        next_state = assert_transition(
            self._state,
            target,
        )

        self._state = next_state

        self._timeline.append(
            StateTimelineEntry(
                state=next_state.value,
                elapsedMs=self.elapsed_ms(),
                timestamp=utc_now_iso(),
            )
        )

        return next_state

    def try_transition(
        self,
        target: HarnessRunState,
    ) -> bool:
        """Transition when legal; otherwise reject and report False.

        Observation paths (OBSERVE mode) use this variant because recording
        must never mutate business behaviour, including state bookkeeping.
        """

        try:
            self.transition(
                target,
            )

            return True

        except InvalidHarnessTransitionError:
            return False

    def timeline(
        self,
    ) -> list[
        StateTimelineEntry,
    ]:
        return list(
            self._timeline,
        )
