"""Asking the user to confirm something irreversible.

Two actions genuinely need to block on an answer — quitting with work in
flight, and re-downloading several gigabytes. Everything else that currently
uses a modal dialog is reporting, not asking, and belongs in a notice.

The port exists so the flow layer can ask without importing ``QMessageBox``.
That keeps the dependency direction intact and makes the decision testable:
a fake that answers yes or no is two lines.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ConfirmationRequest:
    title: str
    body: str
    confirm_label: str = ""
    danger: bool = False


class ConfirmationPort(Protocol):
    def confirm(self, request: ConfirmationRequest) -> bool:
        """Return whether the user agreed. Must default to no."""
        ...


class AlwaysDecline:
    """Fallback for contexts with no window to host a dialog.

    Declining is the only safe default: every caller guards an irreversible
    action, so a missing user must never read as consent.
    """

    def confirm(self, request: ConfirmationRequest) -> bool:
        return False
