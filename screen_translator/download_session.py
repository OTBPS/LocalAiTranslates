"""Model download state and transition rules.

Downloads were tracked by a nullable token that the settings window assigned
to the controller directly, and six places read it to decide whether anything
was busy. A token says "something is happening" and nothing else -- not
whether bytes are moving, whether verification is running, or whether a
cancellation is still winding down.

Deliberately shaped like ``CaptureSession``: an explicit state, a declared
transition table, and a generation counter so that results from a superseded
attempt are discarded rather than applied.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .core import CancellationToken


class DownloadState(StrEnum):
    IDLE = "idle"
    PREPARING = "preparing"
    DOWNLOADING = "downloading"
    VERIFYING = "verifying"
    CANCELLING = "cancelling"
    COMPLETED = "completed"
    FAILED = "failed"


_ALLOWED_TRANSITIONS = {
    DownloadState.IDLE: {DownloadState.PREPARING},
    DownloadState.PREPARING: {
        DownloadState.DOWNLOADING,
        DownloadState.CANCELLING,
        DownloadState.FAILED,
    },
    DownloadState.DOWNLOADING: {
        DownloadState.VERIFYING,
        DownloadState.CANCELLING,
        DownloadState.FAILED,
        DownloadState.COMPLETED,
    },
    DownloadState.VERIFYING: {
        DownloadState.COMPLETED,
        DownloadState.CANCELLING,
        DownloadState.FAILED,
    },
    DownloadState.CANCELLING: {DownloadState.IDLE, DownloadState.FAILED},
    DownloadState.COMPLETED: {DownloadState.IDLE, DownloadState.PREPARING},
    DownloadState.FAILED: {DownloadState.IDLE, DownloadState.PREPARING},
}

ACTIVE_STATES = frozenset(
    {
        DownloadState.PREPARING,
        DownloadState.DOWNLOADING,
        DownloadState.VERIFYING,
        DownloadState.CANCELLING,
    }
)


@dataclass
class DownloadSession:
    attempt: int = 0
    state: DownloadState = DownloadState.IDLE
    token: CancellationToken | None = None
    model_id: str = ""
    file_name: str = ""
    received: int = 0
    total: int = 0
    detail: str = ""

    @property
    def active(self) -> bool:
        return self.state in ACTIVE_STATES

    @property
    def cancellable(self) -> bool:
        return self.state in (DownloadState.PREPARING, DownloadState.DOWNLOADING)

    @property
    def fraction(self) -> float | None:
        """Progress, or ``None`` when the total is not yet known."""
        if self.total <= 0:
            return None
        return max(0.0, min(1.0, self.received / self.total))

    def begin(self, model_id: str) -> int:
        self.attempt += 1
        self.token = CancellationToken()
        self.model_id = model_id
        self.file_name = ""
        self.received = self.total = 0
        self.detail = ""
        self.state = DownloadState.IDLE
        self.transition(DownloadState.PREPARING)
        return self.attempt

    def transition(self, state: DownloadState) -> None:
        if state == self.state:
            return
        if state not in _ALLOWED_TRANSITIONS[self.state]:
            raise RuntimeError(f"无效下载状态：{self.state.value} → {state.value}")
        self.state = state

    def observe(self, file_name: str, received: int, total: int) -> None:
        """Record progress. The first byte is what proves the transfer started."""
        if self.state == DownloadState.PREPARING:
            self.transition(DownloadState.DOWNLOADING)
        self.file_name = file_name
        self.received = max(0, received)
        self.total = max(0, total)

    def invalidate(self) -> int:
        """Cancel the attempt in flight and make late results stale."""
        if self.token:
            self.token.cancel()
        self.attempt += 1
        if self.active:
            self.state = DownloadState.CANCELLING
        return self.attempt

    def finish(self, state: DownloadState, detail: str = "") -> None:
        if state not in (
            DownloadState.COMPLETED,
            DownloadState.FAILED,
            DownloadState.IDLE,
        ):
            raise ValueError(f"不能以 {state.value} 结束下载")
        self.state = state
        self.detail = detail
        self.token = None

    def is_current(self, attempt: int) -> bool:
        return attempt == self.attempt
