from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget


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
    painter.setPen(QPen(QColor(21, 21, 21, 235), 5, Qt.PenStyle.SolidLine))
    for segment in segments:
        painter.drawLine(*segment)
    painter.setPen(QPen(QColor("#F8EBCF"), 2, Qt.PenStyle.SolidLine))
    for segment in segments:
        painter.drawLine(*segment)
    painter.setPen(QPen(QColor(21, 21, 21, 235), 2))
    painter.setBrush(QColor("#E8BC35"))
    painter.drawEllipse(point, 3, 3)
    painter.restore()


class Overlay(QWidget):
    def __init__(self, controller, screen):
        super().__init__()
        self.controller, self.screen = controller, screen
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
        self.timer.start(100)
        self.phase = 0

    def paintEvent(self, event):
        c = self.controller
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.drawImage(self.rect(), self.screen.image)
        if c.state == "selecting":
            p.fillRect(self.rect(), QColor(21, 21, 21, 138))
            if c.selection:
                region = c.selection.translated(-self.screen.geometry.topLeft())
                p.save()
                p.setClipRect(region)
                p.drawImage(self.rect(), self.screen.image)
                p.restore()
                p.setPen(QPen(QColor("#C51D23"), 4))
                p.drawRect(region)
                p.setPen(QPen(QColor("#151515"), 2))
                p.setBrush(QColor("#E8BC35"))
                for corner in (
                    region.topLeft(),
                    region.topRight(),
                    region.bottomLeft(),
                    region.bottomRight(),
                ):
                    p.drawRect(QRect(corner.x() - 5, corner.y() - 5, 10, 10))
                size_text = f"{c.selection.width()} × {c.selection.height()}"
                metrics = p.fontMetrics()
                badge_width = metrics.horizontalAdvance(size_text) + 24
                badge_x = max(12, min(region.left(), self.width() - badge_width - 12))
                badge_y = region.top() - 38 if region.top() >= 92 else region.top() + 10
                badge = QRect(badge_x, badge_y, badge_width, 28)
                p.setPen(QPen(QColor("#151515"), 2))
                p.setBrush(QColor("#E8BC35"))
                p.drawRect(badge)
                p.setPen(QColor("#151515"))
                p.drawText(badge, Qt.AlignmentFlag.AlignCenter, size_text)
        elif c.state == "result" and c.show_translation:
            region = c.capture.logical_rect.translated(-self.screen.geometry.topLeft())
            p.drawImage(region, c.result)

        self.phase += 1
        label = c.message
        if c.state == "working":
            label += "." * (self.phase % 4)
        if c.state == "selecting":
            state_text, state_color = "选择区域", QColor("#C51D23")
        elif c.state == "working":
            state_text, state_color = "正在处理", QColor("#E8BC35")
        elif c.state == "result" and c.show_translation:
            state_text, state_color = "译文", QColor("#C51D23")
        else:
            state_text, state_color = "原图", QColor("#151515")
        if c.state == "result" and hasattr(c, "language_pair_text"):
            label = f"{c.language_pair_text()}  ·  {label}"

        bar_width = max(220, min(820, self.width() - 32))
        bar = QRect((self.width() - bar_width) // 2, 18, bar_width, 58)
        p.setPen(QPen(QColor("#151515"), 3))
        p.setBrush(QColor(243, 233, 210, 246))
        p.drawRect(bar)
        state_rect = QRect(bar.left() + 10, bar.top() + 10, 92, 38)
        p.setPen(QPen(QColor("#151515"), 2))
        p.setBrush(state_color)
        p.drawRect(state_rect)
        p.setPen(QColor("#FFFFFF") if state_color == QColor("#C51D23") else QColor("#151515"))
        state_font = QFont("Microsoft YaHei UI", 10)
        state_font.setWeight(QFont.Weight.Black)
        p.setFont(state_font)
        p.drawText(state_rect, Qt.AlignmentFlag.AlignCenter, state_text)
        detail_rect = QRect(
            state_rect.right() + 14, bar.top(), bar.right() - state_rect.right() - 26, bar.height()
        )
        detail_font = QFont("Microsoft YaHei UI", 10)
        p.setFont(detail_font)
        p.setPen(QColor("#151515"))
        detail = p.fontMetrics().elidedText(label, Qt.TextElideMode.ElideRight, max(20, detail_rect.width()))
        p.drawText(detail_rect, Qt.AlignmentFlag.AlignVCenter, detail)
        if c.state == "selecting":
            global_point = getattr(c, "cursor_point", QCursor.pos())
            if self.screen.geometry.contains(global_point):
                draw_selection_cursor(p, global_point - self.screen.geometry.topLeft())
        p.end()

    def set_interaction_state(self, state: str) -> None:
        if state == "selecting":
            self.setCursor(Qt.CursorShape.BlankCursor)
        elif state == "working":
            self.setCursor(Qt.CursorShape.WaitCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def enterEvent(self, event):
        if self.controller.state == "selecting":
            self.controller.cursor_point = QCursor.pos()
            self.controller.repaint()
        super().enterEvent(event)

    def mousePressEvent(self, event):
        c = self.controller
        if event.button() == Qt.MouseButton.RightButton and c.state == "result":
            c.show_result_language_menu(self, event.globalPosition().toPoint())
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if c.state == "result":
            c.show_translation = not c.show_translation
            c.repaint()
        elif c.state == "selecting":
            c.start_point = event.globalPosition().toPoint()
            c.selection = QRect(c.start_point, c.start_point)
            self.grabMouse()

    def mouseMoveEvent(self, event):
        c = self.controller
        if c.state == "selecting":
            c.cursor_point = event.globalPosition().toPoint()
            if c.start_point is not None:
                c.selection = QRect(c.start_point, c.cursor_point).normalized()
            c.repaint()

    def mouseReleaseEvent(self, event):
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self.controller.state == "selecting"
            and self.controller.start_point is not None
        ):
            self.releaseMouse()
            self.controller.selected()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.controller.cancel()
