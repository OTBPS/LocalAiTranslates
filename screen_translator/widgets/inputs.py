"""Controls whose value the mouse wheel must not change.

A `QComboBox` under the cursor eats the wheel and steps its selection.
On a page that scrolls, that means scrolling past the language row
silently changes the language you translate into, and the only evidence
is the value being wrong later. `QSpinBox` has the identical problem
with the listen port.

Both ignore the wheel instead. **`ignore()` rather than consuming it**:
an ignored wheel event propagates to the parent, so the page underneath
still scrolls — swallowing it would trade one surprise for another.

The dropdown itself is unaffected. `QComboBox.view()` is a separate
widget, so once the list is open the wheel scrolls it normally, which is
what anyone opening a list expects.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QSpinBox, QWidget


class ComboBox(QComboBox):
    """A combo box that is changed by clicking, never by scrolling."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        # StrongFocus, not WheelFocus: the wheel must not even move
        # focus here, or the next keystroke lands somewhere unexpected.
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event):  # noqa: N802 - Qt API spelling
        event.ignore()


class SpinBox(QSpinBox):
    """A spin box that is changed by typing or by its arrows."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event):  # noqa: N802 - Qt API spelling
        event.ignore()
