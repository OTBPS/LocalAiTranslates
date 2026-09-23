"""Composed rows that appear on more than one page.

`LanguageRow` is the 输入语言 / ⇄ / 输出语言 pattern, which both the
capture page and the text page need and which was previously a function
returning four separate values for the caller to reassemble.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QWidget

from ..design import metrics
from .buttons import icon_button
from .fields import Field
from .inputs import ComboBox


class LanguageRow(QWidget):
    """Source, swap, target -- as one widget with named parts."""

    def __init__(
        self,
        source_languages,
        target_languages,
        names,
        parent: QWidget | None = None,
        sizes=None,
    ):
        super().__init__(parent)
        sizes = sizes or metrics.ACTIVE
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(sizes.space_card - 4)

        self.source = ComboBox()
        for code in source_languages:
            self.source.addItem(names[code], code)
        self.target = ComboBox()
        for code in target_languages:
            self.target.addItem(names[code], code)

        self.source_field = Field("输入语言", self.source, sizes=sizes)
        self.target_field = Field("输出语言", self.target, sizes=sizes)
        self.swap = icon_button("swap.svg", "对调输入和输出语言", sizes=sizes)

        row.addWidget(self.source_field, 1)
        # Bottom-aligned so the button sits on the controls' baseline
        # rather than beside their labels.
        row.addWidget(self.swap, 0, Qt.AlignmentFlag.AlignBottom)
        row.addWidget(self.target_field, 1)

    def selection(self) -> tuple[str, str]:
        return self.source.currentData(), self.target.currentData()
