"""Controls that decline the wheel, and one that sizes itself.

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

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFontMetricsF
from PySide6.QtWidgets import QComboBox, QPlainTextEdit, QSizePolicy, QSpinBox, QWidget


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


class GrowingTextEdit(QPlainTextEdit):
    """A text box as tall as what is in it, between two line counts.

    A fixed height has to guess, and the guess is wrong in both
    directions: at 104 px plus a stretch factor this box filled the
    whole page whether it held a paragraph or nothing at all, pushing
    the buttons that act on it below the fold. Sizing it small instead
    would only move the problem -- a paragraph would scroll inside a
    short box while the page around it sat empty.

    Bounds are line counts rather than pixels because that is the unit
    the reader actually perceives, and because a pixel height is only
    correct at one font size and one scale factor. `QPlainTextEdit`
    obliges: its document layout reports its height in lines already,
    wrapped lines included.

    Past the upper bound the box scrolls internally. Growing without
    limit would push the second box and the buttons arbitrarily far
    down, which is the original complaint with a different cause.
    """

    def __init__(
        self,
        *,
        minimum_lines: int,
        maximum_lines: int,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._minimum_lines = minimum_lines
        self._maximum_lines = max(minimum_lines, maximum_lines)
        # Fixed vertically: the height is whatever `sizeHint` says, so a
        # stretch factor in the parent layout cannot override it.
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.document().documentLayout().documentSizeChanged.connect(
            self._content_resized
        )

    def _content_resized(self, _size) -> None:
        self.updateGeometry()

    def _chrome(self) -> int:
        """Everything above the text itself: margins and the frame."""
        return int(2 * self.document().documentMargin()) + 2 * self.frameWidth()

    def _height_for(self, lines: float) -> int:
        spacing = QFontMetricsF(self.font()).lineSpacing()
        return int(round(lines * spacing)) + self._chrome()

    def lines_shown(self) -> float:
        """How many lines tall this box currently wants to be."""
        laid_out = self.document().documentLayout().documentSize().height()
        return max(self._minimum_lines, min(self._maximum_lines, laid_out))

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API spelling
        return QSize(super().sizeHint().width(), self._height_for(self.lines_shown()))

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt API spelling
        return QSize(
            super().minimumSizeHint().width(), self._height_for(self._minimum_lines)
        )
