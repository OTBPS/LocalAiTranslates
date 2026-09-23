"""Status chips and inline messages.

Both follow the same rule: colour is never the only signal. A chip
always carries text, and an inline message always carries a title.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QWidget

from ..design import components, metrics, semantic

ROLES = components.STATUS_ROLES


class StatusChip(QLabel):
    """A short state readout. Text first, colour second."""

    def __init__(self, text: str = "", role: str = "neutral", parent: QWidget | None = None):
        super().__init__(text, parent)
        self.setObjectName("statusChip")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(metrics.ACTIVE.height_control - 8)
        self.set_role(role)

    def set_role(self, role: str) -> None:
        if role not in ROLES:
            role = "neutral"
        self._role = role
        # A dynamic property, so the stylesheet decides the appearance
        # and this class decides nothing about colour.
        self.setProperty("role", role)
        self.style().unpolish(self)
        self.style().polish(self)

    @property
    def role(self) -> str:
        return self._role

    def show_state(self, text: str, role: str = "neutral") -> None:
        self.setText(text)
        self.set_role(role)


class InlineMessage(QWidget):
    """A message attached to one control, rather than to the window.

    The notice banner is for anything about the page or the
    application; this is for the field the user is currently in.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        from PySide6.QtWidgets import QVBoxLayout

        self.setObjectName("inlineMessage")
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        self.label = QLabel()
        self.label.setObjectName("helperText")
        self.label.setWordWrap(True)
        column.addWidget(self.label)
        self.clear()

    def show_message(self, text: str, severity: str = "info") -> None:
        self.label.setText(text)
        self.label.setProperty("severity", severity)
        self.label.style().unpolish(self.label)
        self.label.style().polish(self.label)
        self.setVisible(bool(text))

    def clear(self) -> None:
        self.label.setText("")
        self.setVisible(False)


def chip_palette(role: str, theme=None) -> tuple[str, str]:
    """Fill and text for a role, for anything that paints its own chip."""
    return components.status_chip(theme or semantic.ACTIVE, role)
