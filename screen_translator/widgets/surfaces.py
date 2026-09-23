"""Containers: the card, the inset grouped list, and the hairline.

`Card` replaces `make_card`, and returns a widget with an `add` method
rather than a `(frame, layout)` pair. The pair made every caller hold two
references and decide for itself what the margins should be, which is
why the margins were not the same on every page.
"""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from ..design import metrics


class Divider(QFrame):
    """A hairline. Styled entirely by object name."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("divider")


class Card(QFrame):
    """A titled section. One of these per topic, on every page."""

    def __init__(
        self,
        title: str = "",
        subtitle: str = "",
        parent: QWidget | None = None,
        sizes=None,
    ):
        super().__init__(parent)
        sizes = sizes or metrics.ACTIVE
        self.setObjectName("card")
        self.body = QVBoxLayout(self)
        padding = sizes.space_card + sizes.space_tight
        self.body.setContentsMargins(padding, sizes.space_card + 4, padding, sizes.space_card + 4)
        self.body.setSpacing(sizes.space_card - 2)
        if title:
            heading = QLabel(title)
            heading.setObjectName("sectionTitle")
            self.body.addWidget(heading)
        if subtitle:
            # Helper text only where it says something a label cannot;
            # see the copy rules in the design system.
            hint = QLabel(subtitle)
            hint.setObjectName("helperText")
            hint.setWordWrap(True)
            self.body.addWidget(hint)

    def add(self, item) -> None:
        """Add a widget or a layout, whichever was handed over."""
        if isinstance(item, QWidget):
            self.body.addWidget(item)
        else:
            self.body.addLayout(item)

    def add_divider(self) -> Divider:
        divider = Divider()
        self.body.addWidget(divider)
        return divider


class InsetGroup(QFrame):
    """Rows inside one rounded card, separated by hairlines.

    The main information container in an Apple settings interface, and
    the thing this project was building by hand out of a `Card` and a
    `QVBoxLayout` at every call site. Having it as a widget is what makes
    the separators and the corner inheritance consistent.
    """

    def __init__(self, parent: QWidget | None = None, sizes=None):
        super().__init__(parent)
        sizes = sizes or metrics.ACTIVE
        self.setObjectName("insetGroup")
        self._sizes = sizes
        self._rows: list[QWidget] = []
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

    def add_row(self, widget: QWidget) -> QWidget:
        if self._rows:
            self._layout.addWidget(Divider())
        widget.setObjectName(widget.objectName() or "groupRow")
        self._layout.addWidget(widget)
        self._rows.append(widget)
        return widget

    @property
    def rows(self) -> tuple[QWidget, ...]:
        return tuple(self._rows)


class AppHeader(QWidget):
    """A large title with a secondary line.

    Replaces the painted banner. Liquid Glass does not use colour-block
    headers, and the painted one positioned its decoration at
    `width() - 108`, which ran off the edge at the minimum window size
    and at high DPI. Typography has no such failure mode.
    """

    def __init__(self, title: str, subtitle: str = "", parent: QWidget | None = None, sizes=None):
        super().__init__(parent)
        sizes = sizes or metrics.ACTIVE
        self.setObjectName("appHeader")
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(sizes.space_hair * 2)
        self.title = QLabel(title)
        self.title.setObjectName("appTitle")
        column.addWidget(self.title)
        self.subtitle = QLabel(subtitle)
        self.subtitle.setObjectName("pageSubtitle")
        self.subtitle.setWordWrap(True)
        self.subtitle.setVisible(bool(subtitle))
        column.addWidget(self.subtitle)
