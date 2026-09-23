"""The engines, and everything that keeps them usable.

Choosing a backend, noticing it became ready, and warming it up were three
loops running through the controller and sharing four of its attributes.
Together they are one responsibility: there is exactly one backend at a
time, and this decides which, whether it works, and when it is warm.

Two rules live here because both were learned the hard way. A replacement
that cannot be built must not take the working one down with it -- a remote
backend's session cannot be reopened once closed. And warm-up runs once per
backend, not once per readiness tick: locally a repeat is a cheap no-op,
but remotely every tick became an HTTP round trip and a line in the host
log.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer, Signal

from .backend import Backend
from .contracts import OcrPort, TranslationPort
from .core import CancellationToken, Cancelled, Config
from .feedback import NoticeAction, error_notice
from .navigation import Destination

LOGGER = logging.getLogger(__name__)

# How often readiness is re-checked. The local backend reads the model
# registry and the remote backend pings the host; both are cheap, and
# polling is what lets a client notice that the host came back online.
READINESS_INTERVAL_MS = 15000


class BackendService(QObject):
    """Owns the current backend and the background work that maintains it."""

    changed = Signal()

    def __init__(
        self,
        *,
        factory: Callable[[Config], Backend],
        config_provider: Callable[[], Config],
        tasks,
        notices,
        # In-flight work holds the engines being replaced, so it has to be
        # stopped before the swap rather than after it.
        stop_work: Callable[[], None] = lambda: None,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._factory = factory
        self._config = config_provider
        self._tasks = tasks
        self._notices = notices
        self._stop_work = stop_work
        self._warmup_token: CancellationToken | None = None
        self._readiness_token: CancellationToken | None = None
        self._timer: QTimer | None = None
        self.warmed = False
        self.backend = factory(self._config())

    # -- what the rest of the application reads --------------------------

    @property
    def ocr(self) -> OcrPort:
        return self.backend.ocr

    @property
    def translator(self) -> TranslationPort:
        return self.backend.translator

    @property
    def kind(self) -> str:
        return self.backend.kind

    def ready(self) -> bool:
        return self.backend.ready()

    def describe(self) -> str:
        return self.backend.describe()

    # -- lifecycle -------------------------------------------------------

    def start(self) -> None:
        """Begin polling readiness.

        Kept out of the constructor so tests can drive `poll()` themselves
        instead of waiting on a timer.
        """
        if self._timer is None:
            self._timer = QTimer(self)
            self._timer.setInterval(READINESS_INTERVAL_MS)
            self._timer.timeout.connect(self.poll)
        self._timer.start()
        self.refresh_readiness()

    @property
    def polling(self) -> bool:
        return self._timer is not None and self._timer.isActive()

    def suspend(self) -> None:
        """Stop background maintenance without closing the backend."""
        if self._timer is not None:
            self._timer.stop()
        for token in (self._warmup_token, self._readiness_token):
            if token:
                token.cancel()
        self._warmup_token = self._readiness_token = None

    def stop(self) -> None:
        self.suspend()
        self.backend.stop()

    # -- maintenance -----------------------------------------------------

    def poll(self) -> None:
        """Periodic UI-thread check.

        Both steps are idempotent and read cached state, so this also covers
        the case that matters in remote mode: a host that was offline at
        start-up becomes usable without anyone restarting anything.
        """
        self.refresh_readiness()
        self.warm_up()

    def refresh_readiness(self) -> None:
        if self._readiness_token:
            return
        token = CancellationToken()
        self._readiness_token = token

        def run():
            try:
                self.backend.refresh()
            except Exception as error:
                LOGGER.debug("Readiness refresh failed: %s", type(error).__name__)
            finally:
                if self._readiness_token is token:
                    self._readiness_token = None

        self._tasks.start(run, name="backend-readiness")

    def warm_up(self) -> None:
        """Load the OCR weights, once, while nothing else needs the slot.

        A failure leaves `warmed` clear so the next tick retries, which is
        how a client recovers when the host comes back.
        """
        if self._warmup_token or self.warmed or not self.ready():
            return
        token = CancellationToken()
        self._warmup_token = token
        source_language = self._config().source_language

        def run():
            try:
                self.ocr.warmup(source_language, token, lambda _message: None)
                self.warmed = True
            except Cancelled:
                pass
            except Exception as error:
                LOGGER.warning("OCR warm-up failed: %s", type(error).__name__)
            finally:
                if self._warmup_token is token:
                    self._warmup_token = None

        self._tasks.start(run, name="ocr-warmup")

    def reset_warmup(self) -> None:
        """Forget that the engine is warm, e.g. after the language changed."""
        if self._warmup_token:
            self._warmup_token.cancel()
            self._warmup_token = None
        self.warmed = False

    # -- selection -------------------------------------------------------

    def replace(self) -> bool:
        """Rebuild the backend from the current configuration.

        Returns whether the swap happened. On failure the working backend
        stays in place and the reason is reported where it can be fixed.
        """
        self.reset_warmup()
        self._stop_work()
        try:
            replacement = self._factory(self._config())
        except Exception as error:
            LOGGER.warning("Backend selection failed: %s", type(error).__name__)
            self._notices.post(
                error_notice(
                    "backend-unavailable",
                    "后端不可用",
                    detail=str(error),
                    context="settings",
                    actions=(
                        NoticeAction(
                            "open-remote", "检查跨设备设置", Destination.REMOTE_MODE, primary=True
                        ),
                    ),
                )
            )
            return False
        previous, self.backend = self.backend, replacement
        previous.stop()
        self.changed.emit()
        self.warm_up()
        return True
