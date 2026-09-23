"""A labelled control, with its accessibility wired in by construction.

`Field` calls `setBuddy` and `setAccessibleName` itself. Accessibility
stops being something each call site has to remember and becomes what
happens by default -- and the buddy is also what makes a 36 px input an
acceptable target, because the label is part of its hit area (ADR 0003).
"""

from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QLabel, QVBoxLayout, QWidget

from ..design import metrics


class Field(QWidget):
    """One labelled control."""

    def __init__(
        self,
        label: str,
        control: QWidget,
        helper: str = "",
        parent: QWidget | None = None,
        sizes=None,
    ):
        super().__init__(parent)
        sizes = sizes or metrics.ACTIVE
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(sizes.space_tight - 2)
        self.label = QLabel(label)
        self.label.setObjectName("fieldLabel")
        self.label.setBuddy(control)
        column.addWidget(self.label)
        self.control = control
        if not control.accessibleName():
            control.setAccessibleName(label)
        column.addWidget(control)
        self.helper = QLabel(helper)
        self.helper.setObjectName("helperText")
        self.helper.setWordWrap(True)
        self.helper.setVisible(bool(helper))
        column.addWidget(self.helper)

    def say(self, text: str) -> None:
        self.helper.setText(text)
        self.helper.setVisible(bool(text))


class FieldGrid(QWidget):
    """Fields side by side, sharing a baseline.

    Used for the pairs that belong together -- input and output
    language, listen address and port -- where stacking them would
    suggest they are unrelated.
    """

    def __init__(self, parent: QWidget | None = None, sizes=None):
        super().__init__(parent)
        sizes = sizes or metrics.ACTIVE
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(sizes.space_card - 4)
        self.grid.setVerticalSpacing(sizes.space_tight - 1)
        self._column = 0

    def add(self, field: QWidget, *, stretch: int = 1) -> QWidget:
        self.grid.addWidget(field, 0, self._column)
        self.grid.setColumnStretch(self._column, stretch)
        self._column += 1
        return field
