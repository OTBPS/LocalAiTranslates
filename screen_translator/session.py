"""Capture-session state and transition rules."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .core import CancellationToken


class SessionState(StrEnum):
    IDLE = "idle"
    SELECTING = "selecting"
    # Releasing the mouse used to commit the selection immediately. ADJUSTING
    # is the moment in which a selection exists and can still be corrected.
    ADJUSTING = "adjusting"
    PROCESSING = "working"
    RESULT = "result"
    # A failure used to tear the overlay down and report through a tray
    # balloon, losing the selection and often the message with it. FAILED
    # keeps both on screen so the work can be retried.
    FAILED = "failed"
    CANCELLING = "cancelling"


_ALLOWED_TRANSITIONS = {
    SessionState.IDLE: {SessionState.SELECTING},
    SessionState.SELECTING: {
        SessionState.ADJUSTING,
        SessionState.PROCESSING,
        SessionState.IDLE,
    },
    SessionState.ADJUSTING: {
        SessionState.SELECTING,
        SessionState.PROCESSING,
        SessionState.IDLE,
    },
    SessionState.PROCESSING: {
        SessionState.RESULT,
        SessionState.FAILED,
        SessionState.CANCELLING,
        SessionState.IDLE,
    },
    # RESULT to PROCESSING is retranslation of the capture already in memory.
    SessionState.RESULT: {SessionState.PROCESSING, SessionState.IDLE},
    SessionState.FAILED: {
        SessionState.SELECTING,
        SessionState.PROCESSING,
        SessionState.IDLE,
    },
    SessionState.CANCELLING: {SessionState.IDLE},
}


@dataclass
class CaptureSession:
    generation: int = 0
    state: SessionState = SessionState.IDLE
    token: CancellationToken | None = None

    @property
    def busy(self) -> bool:
        return self.state in (SessionState.PROCESSING, SessionState.CANCELLING)

    def begin(self) -> int:
        self.generation += 1
        self.token = CancellationToken()
        self.transition(SessionState.SELECTING)
        return self.generation

    def transition(self, state: SessionState) -> None:
        if state == self.state:
            return
        if state not in _ALLOWED_TRANSITIONS[self.state]:
            raise RuntimeError(f"无效会话状态：{self.state.value} → {state.value}")
        self.state = state

    def invalidate(self) -> int:
        if self.token:
            self.token.cancel()
        self.generation += 1
        if self.state == SessionState.PROCESSING:
            self.state = SessionState.CANCELLING
        else:
            self.state = SessionState.IDLE
        return self.generation

    def finish_cancel(self) -> None:
        self.state = SessionState.IDLE
        self.token = None

    def is_current(self, generation: int) -> bool:
        return generation == self.generation
