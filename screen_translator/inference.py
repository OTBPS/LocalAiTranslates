"""Arbitration of the single local inference slot.

Screenshot translation and manual text translation share one llama.cpp server.
Running both at once would compete for VRAM and, worse, the fallback path in
``TranslationEngine`` stops the server while another caller is streaming from
it.  Every inference must therefore be wrapped in :meth:`reserve`.

Capture is interactive and hotkey-driven, so it preempts: starting a capture
cancels an in-flight manual translation and manual requests are refused while a
capture is active.
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
        self._manual_token: CancellationToken | None = None

    @property
    def owner(self) -> str | None:
        with self._state:
            return self._owner

    @property
    def capture_active(self) -> bool:
        with self._state:
            return self._capture_active

    def register_manual(self, token: CancellationToken) -> None:
        with self._state:
            self._manual_token = token

    def release_manual(self, token: CancellationToken) -> None:
        with self._state:
            if self._manual_token is token:
                self._manual_token = None

    def cancel_manual(self) -> bool:
        """Cancel an in-flight manual translation. Returns whether one existed."""
        with self._state:
            token = self._manual_token
            self._manual_token = None
        if token is None:
            return False
        token.cancel()
        return True

    def begin_capture(self) -> bool:
        with self._state:
            self._capture_active = True
        return self.cancel_manual()

    def end_capture(self) -> None:
        with self._state:
            self._capture_active = False

    @contextmanager
    def reserve(self, owner: str, *, timeout: float | None = None) -> Iterator[TranslationPort]:
        if owner not in (CAPTURE, MANUAL):
            raise ValueError(f"unknown inference owner: {owner}")
        if owner == CAPTURE:
            self.cancel_manual()
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
