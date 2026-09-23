"""Registration of the global capture shortcut.

The context manager is the point of this module. Applying a shortcut used to
mean registering the new one, remembering the old string in a local variable,
and restoring it from an ``except`` clause further down — which broke the
moment that variable was reused for something else, turning any save failure
into a crash inside the error handler. Scoping the rollback to a ``with``
block makes the pairing impossible to get wrong.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from .native import Hotkey

LOGGER = logging.getLogger(__name__)


class HotkeyService(QObject):
    """Own the registered shortcut and the rules for changing it."""

    changed = Signal(str)

    def __init__(
        self,
        app: QApplication,
        callback: Callable[[], None],
        *,
        backend: Hotkey | None = None,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._backend = backend if backend is not None else Hotkey(callback)
        install = getattr(app, "installNativeEventFilter", None)
        if install is not None:
            install(self._backend)

    @property
    def current(self) -> str:
        return self._backend.current or ""

    def apply(self, sequence: str) -> None:
        """Register ``sequence``. Raises ``ValueError`` and changes nothing on failure."""
        previous = self.current
        self._backend.register(sequence)
        if self.current != previous:
            self.changed.emit(self.current)

    @contextmanager
    def pending(self, sequence: str) -> Iterator[None]:
        """Register ``sequence`` for the duration of the block.

        If the block raises, the previous shortcut is restored before the
        exception propagates, so a failure later in a save leaves the running
        application on the shortcut it actually has.
        """
        previous = self.current
        self.apply(sequence)
        try:
            yield
        except BaseException:
            if previous:
                try:
                    self.apply(previous)
                except ValueError:
                    # The old shortcut was taken while we held the new one.
                    # Nothing better is available; report and keep going so
                    # the original failure is what reaches the user.
                    LOGGER.warning("Could not restore the previous shortcut")
            raise

    def close(self) -> None:
        self._backend.close()
