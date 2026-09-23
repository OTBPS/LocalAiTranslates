"""The full-screen capture chrome.

Painting is driven entirely by an ``OverlayViewModel``; input is translated
into ``CaptureCommand`` values and handed to the controller. Neither side
reaches into the other, which is what lets the capture flow be tested
without a window and the visuals be replaced without touching the flow.
"""

from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QFont, QPainter, QPen
from PySide6.QtWidgets import QMenu, QWidget

from .capture import CaptureCommand, Handle, state_label
from .design import overlay as overlay_palette
from .design.primitives import contrast_ratio
from .session import SessionState

ANIMATION_INTERVAL_MS = 100
NUDGE_STEP = 1
NUDGE_STEP_LARGE = 10
CAPSULE_TOP = 18
CAPSULE_HEIGHT = 78
BADGE_HEIGHT = 28
BADGE_GAP = 10
EDGE_MARGIN = 12
SELECTION_WIDTH = 4

_ARROW_KEYS = {
    Qt.Key.Key_Left: (-1, 0),
    Qt.Key.Key_Right: (1, 0),
    Qt.Key.Key_Up: (0, -1),
    Qt.Key.Key_Down: (0, 1),
}

# What the right-click menu offers, in the order it offers it. Commands
# that are not allowed right now are shown disabled with the reason
# attached, rather than hidden -- an absent entry looks like a missing
# feature.
RESULT_MENU_COMMANDS = (
    CaptureCommand.COPY_TEXT,
    CaptureCommand.COPY_IMAGE,
    CaptureCommand.SAVE_IMAGE,
    CaptureCommand.RETRANSLATE,
    CaptureCommand.SWAP_LANGUAGES,
    CaptureCommand.TOGGLE_VIEW,
)

# The overlay's palette is pinned rather than themed: it paints on an
# unknown screenshot, so whether the application is light or dark says
# nothing about whether the region the user grabbed is. See MASTER.md.
PALETTE = overlay_palette.PINNED

_STATE_COLOURS = {
    SessionState.SELECTING: PALETTE.state_selecting,
    SessionState.ADJUSTING: PALETTE.state_adjusting,
    SessionState.PROCESSING: PALETTE.state_processing,
    SessionState.RESULT: PALETTE.state_result,
    SessionState.FAILED: PALETTE.state_failed,
}


def _label_colour(fill: QColor) -> str:
    """Whichever chrome ink is readable on this state badge.

    Measured rather than keyed off the state name, so adding a state
    colour cannot quietly produce an unreadable label -- which is what
    the previous `white if red else black` would have done.
    """
    inks = (PALETTE.capsule_text, PALETTE.capsule_text_inverse)
    return max(inks, key=lambda ink: contrast_ratio(ink, fill.name().upper()))


def draw_selection_cursor(painter: QPainter, point: QPoint) -> None:
    """Draw a stable, high-contrast cursor without relying on the Windows cursor compositor."""
    gap, radius = 5, 19
    segments = (
        (point.x() - radius, point.y(), point.x() - gap, point.y()),
        (point.x() + gap, point.y(), point.x() + radius, point.y()),
        (point.x(), point.y() - radius, point.x(), point.y() - gap),
        (point.x(), point.y() + gap, point.x(), point.y() + radius),
    )
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    painter.setPen(QPen(QColor(*PALETTE.dim[:3], 235), 5, Qt.PenStyle.SolidLine))
    for segment in segments:
        painter.drawLine(*segment)
    painter.setPen(QPen(QColor(PALETTE.cursor_halo), 2, Qt.PenStyle.SolidLine))
    for segment in segments:
        painter.drawLine(*segment)
    painter.setPen(QPen(QColor(*PALETTE.dim[:3], 235), 2))
    painter.setBrush(QColor(PALETTE.cursor_core))
    painter.drawEllipse(point, 3, 3)
    painter.restore()


class Overlay(QWidget):
    def __init__(self, controller, screen, index=0):
        super().__init__()
        self.controller, self.screen, self.index = controller, screen, index
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool
        )
        self.setGeometry(screen.geometry)
        # Native cross cursors can flicker while Windows transfers ownership
        # between full-screen overlays. The selection cursor is painted below.
        self.setCursor(Qt.CursorShape.BlankCursor)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update)
        self.phase = 0

    # -- painting --------------------------------------------------------

    def model(self):
        return self.controller.overlay_model()

    def local(self, rect):
        origin = self.screen.geometry.topLeft()
        return QRect(
            rect.x - origin.x(), rect.y - origin.y(), rect.width, rect.height
        )

    def paintEvent(self, event):
        model = self.model()
        # Only PROCESSING animates; leaving the timer running in the result
        # state repainted every screen ten times a second for nothing.
        if model.animated and not self.timer.isActive():
            self.timer.start(ANIMATION_INTERVAL_MS)
        elif not model.animated and self.timer.isActive():
            self.timer.stop()

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.drawImage(self.rect(), self.screen.image)
        if model.state in (SessionState.SELECTING, SessionState.ADJUSTING):
            self._paint_selection(painter, model)
        elif model.state == SessionState.RESULT and model.show_translation and model.result:
            painter.drawImage(self.local(model.result_rect), model.result)
        elif model.state == SessionState.FAILED and model.selection:
            self._paint_selection(painter, model, dim=False)

        if self.index == model.capsule_screen:
            self._paint_capsule(painter, model)
        if model.state in (SessionState.SELECTING, SessionState.ADJUSTING) and model.cursor:
            point = QPoint(*model.cursor)
            if self.screen.geometry.contains(point):
                draw_selection_cursor(painter, point - self.screen.geometry.topLeft())
        painter.end()

    def _paint_selection(self, painter, model, *, dim=True):
        if dim:
            painter.fillRect(self.rect(), QColor(*PALETTE.dim))
        if model.selection is None:
            return
        region = self.local(model.selection)
        if dim:
            painter.save()
            painter.setClipRect(region)
            painter.drawImage(self.rect(), self.screen.image)
            painter.restore()
        painter.setPen(QPen(QColor(PALETTE.selection), SELECTION_WIDTH))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(region)
        painter.setPen(QPen(QColor(PALETTE.handle_border), 2))
        painter.setBrush(QColor(PALETTE.handle_fill))
        for _handle, box in model.handles:
            painter.drawRect(self.local(box))

        badge_text = model.badge
        if not badge_text:
            return
        width = painter.fontMetrics().horizontalAdvance(badge_text) + 24
        badge = self._badge_rect(region, width, model)
        painter.setPen(QPen(QColor(PALETTE.badge_text), 2))
        painter.setBrush(QColor(PALETTE.badge_fill))
        painter.drawRect(badge)
        painter.setPen(QColor(PALETTE.badge_text))
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, badge_text)

    def _capsule_rect(self):
        bar_width = max(220, min(820, self.width() - 32))
        return QRect((self.width() - bar_width) // 2, CAPSULE_TOP, bar_width, CAPSULE_HEIGHT)

    def _badge_rect(self, region, width, model):
        """Above the selection when there is room, inside it otherwise.

        "Room" has to account for the capsule, which is painted afterwards
        and therefore on top: the badge used to be measured against the top
        of the screen alone and slid under the status bar for any selection
        starting in the upper third.
        """
        x = max(EDGE_MARGIN, min(region.left(), self.width() - width - EDGE_MARGIN))
        floor = 0
        if self.index == model.capsule_screen:
            floor = self._capsule_rect().bottom() + BADGE_GAP
        above = region.top() - BADGE_HEIGHT - BADGE_GAP
        y = above if above >= floor else max(region.top() + BADGE_GAP, floor)
        y = min(y, self.height() - BADGE_HEIGHT - EDGE_MARGIN)
        return QRect(x, y, width, BADGE_HEIGHT)

    def _paint_capsule(self, painter, model):
        self.phase += 1
        detail = model.message
        if model.state == SessionState.PROCESSING and detail:
            detail += "." * (self.phase % 4)
        if model.state == SessionState.RESULT:
            detail = f"{model.language_pair}  ·  {detail}" if detail else model.language_pair

        # Two rows: what is happening, and what can be done about it. The
        # hint used to share one line and was overwritten by progress text
        # exactly when the wait was longest.
        bar = self._capsule_rect()
        painter.setPen(QPen(QColor(PALETTE.capsule_border), 3))
        painter.setBrush(QColor(*PALETTE.capsule_fill))
        painter.drawRect(bar)

        state_rect = QRect(bar.left() + 10, bar.top() + 10, 92, 38)
        colour = QColor(_STATE_COLOURS.get(model.state, PALETTE.capsule_text))
        painter.setPen(QPen(QColor(PALETTE.capsule_border), 2))
        painter.setBrush(colour)
        painter.drawRect(state_rect)
        painter.setPen(QColor(_label_colour(colour)))
        heading = QFont("Microsoft YaHei UI", 10)
        heading.setWeight(QFont.Weight.Black)
        painter.setFont(heading)
        painter.drawText(state_rect, Qt.AlignmentFlag.AlignCenter, state_label(model))

        body = QFont("Microsoft YaHei UI", 10)
        painter.setFont(body)
        painter.setPen(QColor(PALETTE.capsule_text))
        text_left = state_rect.right() + 14
        width = bar.right() - text_left - 12
        if detail:
            rect = QRect(text_left, bar.top() + 8, width, 24)
            painter.drawText(
                rect,
                Qt.AlignmentFlag.AlignVCenter,
                painter.fontMetrics().elidedText(detail, Qt.TextElideMode.ElideRight, max(20, width)),
            )
        hint_rect = QRect(text_left, bar.top() + (34 if detail else 20), width, 24)
        painter.setPen(QColor(PALETTE.capsule_hint))
        painter.drawText(
            hint_rect,
            Qt.AlignmentFlag.AlignVCenter,
            painter.fontMetrics().elidedText(model.hint, Qt.TextElideMode.ElideRight, max(20, width)),
        )

    def show_result_menu(self, position) -> None:
        """Offer what can actually be done with the result in front of you.

        Previously the only entry swapped the language pair *for the next
        capture*, so the translation on screen could not be copied, saved
        or redone without starting over.
        """
        model = self.model()
        if not model.commands & set(RESULT_MENU_COMMANDS):
            return
        menu = QMenu(self)
        header = menu.addAction(model.language_pair)
        header.setEnabled(False)
        menu.addSeparator()
        for command in RESULT_MENU_COMMANDS:
            action = menu.addAction(command.label)
            action.setEnabled(model.allows(command))
            if not model.allows(command):
                action.setToolTip(self.controller.explain(command))
            action.triggered.connect(
                lambda _checked=False, chosen=command: self.controller.handle(chosen)
            )
        menu.popup(position)
        self.result_menu = menu

    def set_interaction_state(self, state: str) -> None:
        if state == "working":
            self.setCursor(Qt.CursorShape.WaitCursor)
        elif state == "result":
            self.setCursor(Qt.CursorShape.ArrowCursor)
        else:
            self.setCursor(Qt.CursorShape.BlankCursor)

    # -- input -----------------------------------------------------------

    def enterEvent(self, event):
        self.controller.cursor_point = QCursor.pos()
        self.controller.repaint()
        super().enterEvent(event)

    def mousePressEvent(self, event):
        point = event.globalPosition().toPoint()
        self.controller.cursor_point = point
        if event.button() == Qt.MouseButton.RightButton:
            self.show_result_menu(point)
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        model = self.model()
        if model.allows(CaptureCommand.TOGGLE_VIEW):
            self.controller.handle(CaptureCommand.TOGGLE_VIEW)
            return
        handle = self._handle_at(model, point)
        if handle is not None and model.allows(CaptureCommand.GRAB_HANDLE):
            self.controller.handle(CaptureCommand.GRAB_HANDLE, (handle, (point.x(), point.y())))
            self.grabMouse()
            return
        if self.controller.handle(CaptureCommand.BEGIN_DRAG, (point.x(), point.y())):
            self.grabMouse()

    def mouseMoveEvent(self, event):
        point = event.globalPosition().toPoint()
        self.controller.cursor_point = point
        model = self.model()
        if model.state == SessionState.ADJUSTING:
            self.controller.handle(CaptureCommand.DRAG_HANDLE, (point.x(), point.y()))
        elif model.state == SessionState.SELECTING:
            self.controller.handle(CaptureCommand.UPDATE_DRAG, (point.x(), point.y()))
        else:
            self.controller.repaint()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        point = event.globalPosition().toPoint()
        model = self.model()
        self.releaseMouse()
        if model.state == SessionState.ADJUSTING:
            self.controller.handle(CaptureCommand.RELEASE_HANDLE)
        else:
            self.controller.handle(CaptureCommand.END_DRAG, (point.x(), point.y()))

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.controller.handle(CaptureCommand.CONFIRM)

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.controller.handle(CaptureCommand.CANCEL)
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            model = self.model()
            command = (
                CaptureCommand.RETRY
                if model.state == SessionState.FAILED
                else CaptureCommand.CONFIRM
            )
            self.controller.handle(command)
            return
        if key == Qt.Key.Key_R:
            self.controller.handle(CaptureCommand.RESELECT)
            return
        if key in _ARROW_KEYS:
            step = (
                NUDGE_STEP_LARGE
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                else NUDGE_STEP
            )
            dx, dy = _ARROW_KEYS[key]
            handle = (
                Handle.BOTTOM_RIGHT
                if event.modifiers() & Qt.KeyboardModifier.ControlModifier
                else Handle.BODY
            )
            self.controller.handle(CaptureCommand.NUDGE, (handle, dx * step, dy * step))
            return
        super().keyPressEvent(event)

    def _handle_at(self, model, point):
        for handle, box in model.handles:
            if self.local(box).adjusted(-10, -10, 10, 10).contains(
                point - self.screen.geometry.topLeft()
            ):
                return handle
        return None
