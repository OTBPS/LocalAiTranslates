"""Capture-session state and transition rules."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .core import CancellationToken


class SessionState(StrEnum):
    IDLE = "idle"
    SELECTING = "selecting"
    PROCESSING = "working"
    RESULT = "result"
    CANCELLING = "cancelling"


_ALLOWED_TRANSITIONS = {
    SessionState.IDLE: {SessionState.SELECTING},
    SessionState.SELECTING: {SessionState.PROCESSING, SessionState.IDLE},
    SessionState.PROCESSING: {SessionState.RESULT, SessionState.CANCELLING, SessionState.IDLE},
    SessionState.RESULT: {SessionState.IDLE},
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
