"""Where notices actually appear.

Only this module knows about widgets. The tray sink is deliberately last
resort: Windows Focus Assist and notification settings can swallow balloons
without telling the application, so a failure that only went there is a
failure the user may never see.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from ..design import metrics
from .notices import Notice, Severity, Surface

#: Read once: a stylesheet reload does not rebuild these widgets.
SIZES = metrics.ACTIVE

_TRAY_ICON = {
    Severity.ERROR: QSystemTrayIcon.MessageIcon.Critical,
    Severity.WARNING: QSystemTrayIcon.MessageIcon.Warning,
}


class TraySink:
    """Fallback surface. Never the only place an error is reported."""

    surface = Surface.TRAY

    def __init__(self, tray: QSystemTrayIcon):
        self._tray = tray

    def available(self) -> bool:
        return bool(self._tray) and self._tray.isVisible()

    def present(self, notice: Notice) -> None:
        body = notice.detail or notice.title
        icon = _TRAY_ICON.get(notice.severity, QSystemTrayIcon.MessageIcon.Information)
        self._tray.showMessage(notice.title, body, icon)

    def revoke(self, notice_id: str) -> None:
        """Balloons cannot be recalled; they expire on their own."""


class NoticeBanner(QWidget):
    """An in-page message with room for the actions that resolve it."""

    action_invoked = Signal(str, str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("noticeBanner")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SIZES.space_tight)

        self._frame = QFrame()
        self._frame.setObjectName("noticeCard")
        inner = QVBoxLayout(self._frame)
        inner.setContentsMargins(
            SIZES.space_card, SIZES.space_row, SIZES.space_card, SIZES.space_row
        )
        inner.setSpacing(SIZES.space_tight)

        self._title = QLabel()
        self._title.setObjectName("noticeTitle")
        self._title.setWordWrap(True)
        inner.addWidget(self._title)

        self._detail = QLabel()
        self._detail.setObjectName("helperText")
        self._detail.setWordWrap(True)
        self._detail.hide()
        inner.addWidget(self._detail)

        self._progress = QProgressBar()
        self._progress.setRange(0, 1000)
        self._progress.setTextVisible(False)
        self._progress.hide()
        inner.addWidget(self._progress)

        self._actions = QHBoxLayout()
        self._actions.setSpacing(SIZES.space_tight)
        self._actions.addStretch()
        inner.addLayout(self._actions)

        layout.addWidget(self._frame)
        self._buttons: list[QPushButton] = []
        self._notice: Notice | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.clear)
        self.hide()

    @property
    def notice(self) -> Notice | None:
        return self._notice

    def show_notice(self, notice: Notice) -> None:
        self._notice = notice
        self._title.setText(notice.title)
        self._detail.setText(notice.detail)
        self._detail.setVisible(bool(notice.detail))
        self._restyle(str(notice.severity))

        if notice.severity == Severity.PROGRESS:
            self._progress.show()
            if notice.progress is None:
                self._progress.setRange(0, 0)
            else:
                self._progress.setRange(0, 1000)
                self._progress.setValue(int(notice.progress * 1000))
        else:
            self._progress.hide()

        self._rebuild_actions(notice)
        self.show()
        self._timer.stop()
        if not notice.persistent and notice.timeout_ms > 0:
            self._timer.start(notice.timeout_ms)

    def _restyle(self, severity: str) -> None:
        """Re-evaluate the stylesheet for the card and everything inside it.

        Repolishing only the frame leaves its labels on the rules they were
        first matched against, so an error card ends up with muted grey
        detail text on a red fill -- unreadable, and easy to miss because the
        title above it does change colour.
        """
        self._frame.setProperty("severity", severity)
        for widget in (self._frame, *self._frame.findChildren(QWidget)):
            widget.setProperty("severity", severity)
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def clear(self) -> None:
        self._timer.stop()
        self._notice = None
        self.hide()

    def revoke(self, notice_id: str) -> None:
        if self._notice is not None and self._notice.notice_id == notice_id:
            self.clear()

    def _rebuild_actions(self, notice: Notice) -> None:
        for button in self._buttons:
            self._actions.removeWidget(button)
            button.deleteLater()
        self._buttons = []
        for action in notice.actions:
            button = QPushButton(action.label)
            button.setAccessibleName(action.label)
            if action.primary:
                button.setObjectName("primaryButton")
            button.clicked.connect(
                self._emitter(notice.notice_id, action.action_id)
            )
            self._actions.addWidget(button)
            self._buttons.append(button)

    def _emitter(self, notice_id: str, action_id: str) -> Callable[[], None]:
        def emit(_checked: bool = False) -> None:
            self.action_invoked.emit(notice_id, action_id)

        return emit


class BannerSink:
    """Presents notices in a page banner, optionally filtered by context."""

    surface = Surface.INLINE

    def __init__(self, banner: NoticeBanner, *, context: str = ""):
        self._banner = banner
        self._context = context

    def available(self) -> bool:
        window = self._banner.window()
        return bool(window) and window.isVisible()

    def present(self, notice: Notice) -> None:
        if self._context and notice.context != self._context:
            return
        self._banner.show_notice(notice)

    def revoke(self, notice_id: str) -> None:
        self._banner.revoke(notice_id)


class OverlaySink:
    """The capture overlay's own capsule.

    Available only while an overlay is on screen, which is precisely when a
    capture failure should stay in front of the user instead of vanishing
    into a balloon.
    """

    surface = Surface.OVERLAY

    def __init__(self, present: Callable[[Notice], None], is_visible: Callable[[], bool]):
        self._present = present
        self._is_visible = is_visible

    def available(self) -> bool:
        return self._is_visible()

    def present(self, notice: Notice) -> None:
        self._present(notice)

    def revoke(self, notice_id: str) -> None:
        """The overlay shows one message at a time; the next one replaces it."""


def alignment_hint() -> Qt.AlignmentFlag:
    return Qt.AlignmentFlag.AlignTop
