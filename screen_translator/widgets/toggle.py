"""The switch, and the row it usually lives in.

`ToggleSwitch` paints itself, which is exactly why its six colours used
to be literals: QSS cannot reach `QAbstractButton.paintEvent`. They now
come from `design.components.toggle`, the same function the stylesheet
generator reads, so the switch and everything around it cannot drift
apart.

The animation and the reduced-motion handling are unchanged. Only the
geometry and where the colours come from have moved.
"""

from __future__ import annotations

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPropertyAnimation,
    QRectF,
    Qt,
)
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from ..design import components, metrics, semantic
from ..native import animations_enabled

ANIMATION_MS = 120


class ToggleSwitch(QAbstractButton):
    """Keyboard-accessible switch."""

    def __init__(self, parent: QWidget | None = None, theme=None, sizes=None):
        super().__init__(parent)
        self._tokens = components.toggle(theme or semantic.ACTIVE, sizes or metrics.ACTIVE)
        self._sizes = sizes or metrics.ACTIVE
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedSize(self._tokens.width + 6, self._sizes.height_control)
        self._position = 0.0
        self._animation = QPropertyAnimation(self, b"position", self)
        self._animation.setDuration(ANIMATION_MS)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate_to_state)

    def _get_position(self) -> float:
        return self._position

    def _set_position(self, value: float) -> None:
        self._position = value
        self.update()

    position = Property(float, _get_position, _set_position)

    def _animate_to_state(self, checked: bool) -> None:
        self._animation.stop()
        if not animations_enabled():
            self._set_position(1.0 if checked else 0.0)
            return
        self._animation.setStartValue(self._position)
        self._animation.setEndValue(1.0 if checked else 0.0)
        self._animation.start()

    def setChecked(self, checked: bool) -> None:  # noqa: N802 - Qt API spelling
        super().setChecked(checked)
        if not self.isVisible():
            # State must be correct before the first paint; an animation
            # that has not run yet is not an excuse for drawing "off".
            self._animation.stop()
            self._position = 1.0 if checked else 0.0
            self.update()

    def paintEvent(self, event):
        tokens = self._tokens
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        inset = (self.height() - tokens.height) / 2
        track = QRectF(2, inset, tokens.width, tokens.height)
        if not self.isEnabled():
            fill = tokens.disabled_track
        elif self.isChecked():
            fill = tokens.track_on
        else:
            fill = tokens.track_off
        painter.setPen(QPen(QColor(tokens.track_border), self._sizes.border))
        painter.setBrush(QColor(fill))
        radius = min(tokens.radius, tokens.height / 2)
        painter.drawRoundedRect(track, radius, radius)

        travel = tokens.width - tokens.height
        knob = QRectF(
            5 + travel * self._position,
            inset + 3,
            tokens.height - 6,
            tokens.height - 6,
        )
        painter.setPen(QPen(QColor(tokens.knob_border), self._sizes.border))
        painter.setBrush(QColor(tokens.knob))
        knob_radius = min(radius, knob.height() / 2)
        painter.drawRoundedRect(knob, knob_radius, knob_radius)

        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(self._theme_focus()), self._sizes.focus_border))
            ring = QRectF(self.rect()).adjusted(1, inset - 3, -1, -(inset - 3))
            painter.drawRoundedRect(ring, radius + 3, radius + 3)
        painter.end()

    def _theme_focus(self) -> str:
        return semantic.ACTIVE.focus


class ToggleRow(QWidget):
    """A labelled preference with its switch on the right."""

    def __init__(self, title: str, subtitle: str, accessible_name: str, parent=None, sizes=None):
        super().__init__(parent)
        sizes = sizes or metrics.ACTIVE
        self.setObjectName("settingRow")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 2, 0, 2)
        row.setSpacing(sizes.space_card)
        copy = QVBoxLayout()
        copy.setSpacing(2)
        self.title = QLabel(title)
        self.title.setObjectName("rowTitle")
        self.title.setMinimumWidth(0)
        # Ignored rather than Preferred: at the minimum window width the
        # switch must keep its size and the text must elide, not the
        # other way round.
        self.title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        copy.addWidget(self.title)
        if subtitle:
            self.subtitle = QLabel(subtitle)
            self.subtitle.setObjectName("rowSubtitle")
            self.subtitle.setWordWrap(True)
            self.subtitle.setMinimumWidth(0)
            self.subtitle.setSizePolicy(
                QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
            )
            copy.addWidget(self.subtitle)
        row.addLayout(copy, 1)
        self.switch = ToggleSwitch(sizes=sizes)
        self.switch.setAccessibleName(accessible_name)
        if subtitle:
            self.switch.setToolTip(subtitle)
        row.addWidget(self.switch, 0, Qt.AlignmentFlag.AlignVCenter)
