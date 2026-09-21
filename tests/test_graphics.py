import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"
import pytest
from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QFontDatabase, QImage
from PySide6.QtWidgets import QApplication

from screen_translator.core import CancellationToken, OcrLine, TextBlock, TranslatedBlock
from screen_translator.graphics import OverlayRenderer, ScreenShot, capture_region, fitted_text


@pytest.fixture(scope="module", autouse=True)
def app():
    instance = QApplication.instance() or QApplication([])
    QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
    yield instance


@pytest.mark.parametrize("scale", [1, 1.25, 1.5, 2])
def test_cross_screen_negative_coordinates(scale):
    left = QImage(round(200 * scale), round(100 * scale), QImage.Format.Format_RGB888)
    left.fill(QColor("red"))
    right = QImage(200, 100, QImage.Format.Format_RGB888)
    right.fill(QColor("blue"))
    capture = capture_region(
        [ScreenShot(QRect(-200, 0, 200, 100), left, scale), ScreenShot(QRect(0, 0, 200, 100), right, 1)],
        QRect(-50, 0, 100, 100),
    )
    assert capture.image.width() == round(100 * scale)
    assert capture.image.pixelColor(0, 0) == QColor("red")
    assert capture.image.pixelColor(capture.image.width() - 1, 0) == QColor("blue")


def test_long_text_truncates():
    font, text, truncated = fitted_text("很长的翻译内容" * 100, 90, 30, 20)
    assert truncated and text.endswith("…") and font.pixelSize() == 11


def test_render_preserves_original():
    original = QImage(400, 200, QImage.Format.Format_RGB888)
    original.fill(QColor("white"))
    block = TextBlock("0", [OcrLine([(10, 10), (150, 10), (150, 40), (10, 40)], "Hello", 0.99)])
    result = OverlayRenderer().render(original, [TranslatedBlock(block, "你好，世界")], CancellationToken())
    assert result != original
    assert original.pixelColor(20, 20) == QColor("white")


def test_render_expands_only_into_free_space_in_same_column():
    original = QImage(500, 240, QImage.Format.Format_RGB888)
    original.fill(QColor("white"))
    first = TextBlock(
        "0",
        [OcrLine([(10, 10), (240, 10), (240, 32), (10, 32)], "Long source", 0.99)],
        column_index=0,
    )
    second = TextBlock(
        "1",
        [OcrLine([(10, 150), (240, 150), (240, 172), (10, 172)], "Next source", 0.99)],
        column_index=0,
    )
    translated = [
        TranslatedBlock(first, "需要自动换行并使用空白区域的较长翻译文本" * 3),
        TranslatedBlock(second, "下一段"),
    ]

    OverlayRenderer().render(original, translated, CancellationToken())

    first_rect = QRect(*translated[0].draw_rect)
    second_rect = QRect(*translated[1].draw_rect)
    assert first_rect.bottom() < second_rect.top()
    assert translated[0].font_size >= 11
