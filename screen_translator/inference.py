"""Arbitration of the single local inference slot.

Screenshot translation, manual text translation and requests from another
device over the tailnet all share one llama.cpp server.  Running two at once
would compete for VRAM and, worse, the fallback path in ``TranslationEngine``
stops the server while another caller is streaming from it.  Every inference
must therefore be wrapped in :meth:`reserve`.

Capture is interactive and hotkey-driven, so it preempts everything: starting a
capture cancels in-flight manual and remote work, and both are refused while a
capture is active.  Manual and remote requests are otherwise peers; because
several remote requests can be in flight at once, preemptable work is tracked
as a set rather than a single token.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from .contracts import TranslationPort
from .core import CancellationToken

LOGGER = logging.getLogger(__name__)

CAPTURE = "capture"
MANUAL = "manual"
REMOTE = "remote"
_PREEMPTABLE_OWNERS = (MANUAL, REMOTE)
CAPTURE_TIMEOUT = 20.0


class InferenceBusy(RuntimeError):
    """Raised when the inference slot cannot be granted to a caller."""


class InferenceCoordinator:
    """Grant exclusive use of the shared translation engine to one caller."""

    def __init__(self, provider: Callable[[], TranslationPort]):
        self._provider = provider
        self._slot = threading.Semaphore(1)
        self._state = threading.Lock()
        self._owner: str | None = None
        self._capture_active = False
        self._preemptable: list[CancellationToken] = []

    @property
    def owner(self) -> str | None:
        with self._state:
            return self._owner

    @property
    def capture_active(self) -> bool:
        with self._state:
            return self._capture_active

    @property
    def preemptable_tokens(self) -> tuple[CancellationToken, ...]:
        with self._state:
            return tuple(self._preemptable)

    def register_preemptable(self, token: CancellationToken) -> None:
        """Track work that a capture is allowed to cancel."""
        with self._state:
            self._preemptable.append(token)

    def release_preemptable(self, token: CancellationToken) -> None:
        with self._state:
            self._preemptable = [item for item in self._preemptable if item is not token]

    def cancel_preemptable(self) -> bool:
        """Cancel all in-flight manual and remote work. Returns whether any existed."""
        with self._state:
            tokens = self._preemptable
            self._preemptable = []
        for token in tokens:
            token.cancel()
        return bool(tokens)

    # Names kept so the manual translation controller and its tests keep
    # reading the way they did before remote requests joined the same queue.
    register_manual = register_preemptable
    release_manual = release_preemptable
    cancel_manual = cancel_preemptable

    def begin_capture(self) -> bool:
        with self._state:
            self._capture_active = True
        return self.cancel_preemptable()

    def end_capture(self) -> None:
        with self._state:
            self._capture_active = False

    @contextmanager
    def reserve(self, owner: str, *, timeout: float | None = None) -> Iterator[TranslationPort]:
        if owner not in (CAPTURE, *_PREEMPTABLE_OWNERS):
            raise ValueError(f"unknown inference owner: {owner}")
        if owner == CAPTURE:
            self.cancel_preemptable()
            wait = CAPTURE_TIMEOUT if timeout is None else timeout
        else:
            if self.capture_active:
                raise InferenceBusy("截图翻译正在进行，请稍后再试")
            wait = 0.0 if timeout is None else timeout
        if not self._slot.acquire(timeout=wait):
            raise InferenceBusy("本地模型正忙，请稍后再试")
        with self._state:
            self._owner = owner
        try:
            yield self._provider()
        finally:
            with self._state:
                self._owner = None
            self._slot.release()
