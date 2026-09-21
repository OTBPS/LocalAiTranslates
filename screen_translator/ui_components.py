"""Reusable desktop controls for the constructivist settings experience."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Property, QEasingCurve, QPointF, QPropertyAnimation, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .native import animations_enabled


def asset_path(name: str) -> str:
    return str(Path(__file__).with_name("assets") / name)


class ConstructivistHero(QFrame):
    """A flat geometric banner inspired by Soviet constructivist composition."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("heroCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        painter.setPen(QPen(QColor("#151515"), 2))
        painter.setBrush(QColor("#C51D23"))
        painter.drawRect(rect)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#151515"))
        painter.drawPolygon(
            QPolygonF(
                [
                    QPointF(self.width() * 0.68, 0),
                    QPointF(self.width(), 0),
                    QPointF(self.width(), self.height()),
                    QPointF(self.width() * 0.52, self.height()),
                ]
            )
        )
        painter.setBrush(QColor("#E8BC35"))
        painter.drawEllipse(QRectF(self.width() - 108, 14, 72, 72))
        painter.end()


class ToggleSwitch(QAbstractButton):
    """Keyboard-accessible rectangular mechanical switch."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedSize(56, 44)
        self._position = 0.0
        self._animation = QPropertyAnimation(self, b"position", self)
        self._animation.setDuration(120)
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
            self._animation.stop()
            self._position = 1.0 if checked else 0.0
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        track = QRectF(2, 9, 52, 26)
        if not self.isEnabled():
            background = QColor("#C9C0AE")
        elif self.isChecked():
            background = QColor("#C51D23")
        else:
            background = QColor("#F8F1E2")
        painter.setPen(QPen(QColor("#151515"), 2))
        painter.setBrush(background)
        painter.drawRect(track)

        knob_x = 5 + (25 * self._position)
        painter.setPen(QPen(QColor("#151515"), 2))
        painter.setBrush(QColor("#E8BC35") if self.isChecked() else QColor("#FFFFFF"))
        painter.drawRect(QRectF(knob_x, 12, 20, 20))
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor("#C51D23"), 3))
            painter.drawRect(QRectF(0.5, 6.5, 55, 31))
        painter.end()


class ToggleRow(QWidget):
    """A labeled settings row that keeps the whole preference easy to scan."""

    def __init__(self, title: str, subtitle: str, accessible_name: str, parent=None):
        super().__init__(parent)
        self.setObjectName("settingRow")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 2, 0, 2)
        row.setSpacing(16)
        copy = QVBoxLayout()
        copy.setSpacing(2)
        title_label = QLabel(title)
        title_label.setObjectName("rowTitle")
        title_label.setMinimumWidth(0)
        title_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        copy.addWidget(title_label)
        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setObjectName("rowSubtitle")
            subtitle_label.setWordWrap(True)
            subtitle_label.setMinimumWidth(0)
            subtitle_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            copy.addWidget(subtitle_label)
        row.addLayout(copy, 1)
        self.switch = ToggleSwitch()
        self.switch.setAccessibleName(accessible_name)
        if subtitle:
            self.switch.setToolTip(subtitle)
        row.addWidget(self.switch, 0, Qt.AlignmentFlag.AlignVCenter)
