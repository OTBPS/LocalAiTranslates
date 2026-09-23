"""Naming places in the settings window so other layers can point at them.

An error that says what went wrong but not where to fix it leaves the user to
hunt through three tabs. The existing code had exactly one hard-coded jump
(focus the language controls); everything else could only open the window at
whatever tab it happened to be on. A destination is an identifier a message
can carry, so "model not downloaded" can offer a button that lands on the
download control instead of describing where it lives.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol


class Destination(StrEnum):
    CAPTURE_LANGUAGES = "capture.languages"
    CAPTURE_STATUS = "capture.status"
    TEXT_INPUT = "text.input"
    SYSTEM_HOTKEY = "system.hotkey"
    MODEL_SELECTION = "system.model"
    MODEL_DOWNLOAD = "system.model.download"
    MODEL_DIRECTORY = "system.model.directory"
    REMOTE_MODE = "system.remote.mode"
    REMOTE_PAIRING = "system.remote.pairing"
    HOST_SERVICE = "system.remote.host"


class Navigator(Protocol):
    def navigate(self, destination: Destination, *, focus: bool = True) -> bool:
        """Reveal ``destination``. Returns whether it is known to this view."""
        ...
