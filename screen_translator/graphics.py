from dataclasses import dataclass

import cv2
import numpy as np
from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter


def to_array(image):
    image = image.convertToFormat(QImage.Format.Format_RGB888)
    return (
        np.frombuffer(image.bits(), np.uint8)
        .reshape(image.height(), image.bytesPerLine())[:, : image.width() * 3]
        .reshape(image.height(), image.width(), 3)
        .copy()
    )


def to_bgr(image):
    """Convert a Qt image to the BGR array OCR expects.

    The conversion lives here rather than in the pipeline so that the
    pipeline has no OpenCV import to satisfy, and can therefore be tested
    with a plain array factory and no Qt application.
    """
    return cv2.cvtColor(to_array(image), cv2.COLOR_RGB2BGR)


def from_array(array):
    array = np.ascontiguousarray(array)
    return QImage(
        array.data, array.shape[1], array.shape[0], array.strides[0], QImage.Format.Format_RGB888
    ).copy()


@dataclass
class ScreenShot:
    geometry: QRect
    image: QImage
    scale: float


@dataclass
class CaptureRegion:
    logical_rect: QRect
    image: QImage
    scale: float
    screens: list[ScreenShot]


def capture_region(screens, rect):
    scale = max(s.scale for s in screens if s.geometry.intersects(rect))
    image = QImage(round(rect.width() * scale), round(rect.height() * scale), QImage.Format.Format_RGB888)
    image.fill(Qt.GlobalColor.black)
    painter = QPainter(image)
    for screen in screens:
        part = rect.intersected(screen.geometry)
        if part.isEmpty():
            continue
        target = QRectF(
            (part.x() - rect.x()) * scale,
            (part.y() - rect.y()) * scale,
            part.width() * scale,
            part.height() * scale,
        )
        source = QRectF(
            (part.x() - screen.geometry.x()) * screen.scale,
            (part.y() - screen.geometry.y()) * screen.scale,
            part.width() * screen.scale,
            part.height() * screen.scale,
        )
        painter.drawImage(target, screen.image, source)
    painter.end()
    return CaptureRegion(rect, image, scale, screens)


FONT_FAMILIES = {
    "zh-Hans": ["Microsoft YaHei UI", "Microsoft YaHei"],
    "en": ["Segoe UI", "Arial"],
    "ja": ["Yu Gothic UI", "Meiryo UI", "Microsoft YaHei UI"],
    "ko": ["Malgun Gothic", "Microsoft YaHei UI"],
}


def fitted_text(text, width, height, initial, minimum=11, language="zh-Hans"):
    flags = Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
    for size in range(max(initial, minimum), minimum - 1, -1):
        font = QFont()
        font.setFamilies(FONT_FAMILIES.get(language, FONT_FAMILIES["zh-Hans"]))
        font.setPixelSize(size)
        metrics = QFontMetrics(font)
        bounds = metrics.boundingRect(QRect(0, 0, width, 100000), int(flags), text)
        if bounds.height() <= height and bounds.width() <= width:
            return font, text, False
    low, high = 0, len(text)
    while low < high:
        mid = (low + high + 1) // 2
        bounds = metrics.boundingRect(QRect(0, 0, width, 100000), int(flags), text[:mid] + "…")
        if bounds.height() <= height and bounds.width() <= width:
            low = mid
        else:
            high = mid - 1
    return font, text[:low] + "…", True


class OverlayRenderer:
    def render(self, original, translated, token, target_language="zh-Hans"):
        rgb = to_array(original)
        mask = np.zeros(rgb.shape[:2], np.uint8)
        for item in translated:
            if item.text == item.block.text:
                continue
            for line in item.block.lines:
                cv2.fillPoly(mask, [np.array(line.polygon, np.int32)], 255)
        repaired = cv2.inpaint(rgb, cv2.dilate(mask, np.ones((3, 3), np.uint8)), 3, cv2.INPAINT_TELEA)
        image = from_array(repaired)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        reserved = [
            QRect(
                int(b.block.rect[0]),
                int(b.block.rect[1]),
                int(b.block.rect[2] - b.block.rect[0]) + 1,
                int(b.block.rect[3] - b.block.rect[1]) + 1,
            )
            for b in translated
        ]
        try:
            for index, item in enumerate(translated):
                token.check()
                if item.text == item.block.text:
                    continue
                rect = reserved[index].intersected(image.rect())
                initial = max(
                    11,
                    int(np.median([line.rect[3] - line.rect[1] for line in item.block.lines]) * 0.85),
                )
                minimum = max(11, round(initial * 0.6))
                font, text, clipped = fitted_text(
                    item.text,
                    rect.width(),
                    rect.height(),
                    initial,
                    minimum=minimum,
                    language=target_language,
                )
                if clipped:
                    next_tops = [
                        other.top()
                        for j, other in enumerate(reserved)
                        if j != index
                        and translated[j].block.column_index == item.block.column_index
                        and other.top() > rect.bottom()
                    ]
                    available_bottom = min(next_tops) - 4 if next_tops else image.height() - 1
                    expanded = QRect(
                        rect.left(),
                        rect.top(),
                        rect.width(),
                        max(rect.height(), available_bottom - rect.top() + 1),
                    ).intersected(image.rect())
                    if not any(
                        expanded.intersects(other)
                        for j, other in enumerate(reserved)
                        if index != j and translated[j].block.column_index == item.block.column_index
                    ):
                        rect = expanded
                        reserved[index] = expanded
                        font, text, clipped = fitted_text(
                            item.text,
                            rect.width(),
                            rect.height(),
                            initial,
                            minimum=minimum,
                            language=target_language,
                        )
                patch = rgb[rect.top() : rect.bottom() + 1, rect.left() : rect.right() + 1]
                if patch.size == 0:
                    continue
                background = np.median(
                    np.concatenate([patch[0], patch[-1], patch[:, 0], patch[:, -1]]), axis=0
                )
                if clipped or np.std(patch.astype(float), axis=(0, 1)).mean() > 45:
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor(*[int(v) for v in background], 245))
                    painter.drawRoundedRect(rect, 3, 3)
                painter.setPen(QColor("#161b22") if background.mean() > 125 else QColor("#ffffff"))
                painter.setFont(font)
                painter.drawText(
                    rect,
                    int(Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop),
                    text,
                )
                item.draw_rect = rect.getRect()
                item.font_size = font.pixelSize()
        finally:
            painter.end()
        return image
