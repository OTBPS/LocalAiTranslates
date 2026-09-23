"""Render each capture-overlay state offscreen for repeatable visual review.

The overlay is the one surface that cannot be inspected by opening a window:
it only exists between a hotkey press and a result. Every state is built
here from a view model, on a backdrop that is bright on one side and dark on
the other, so chrome contrast can be judged against both.
"""

from __future__ import annotations

import os
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtCore import QRect  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QColor,
    QFont,
    QFontDatabase,
    QImage,
    QLinearGradient,
    QPainter,
)
from PySide6.QtWidgets import QApplication  # noqa: E402

from screen_translator.capture import (  # noqa: E402
    OverlayViewModel,
    Rect,
    SelectionModel,
    allowed_commands,
    default_hint,
)
from screen_translator.graphics import ScreenShot  # noqa: E402
from screen_translator.overlay import Overlay  # noqa: E402
from screen_translator.session import SessionState  # noqa: E402

WIDTH, HEIGHT = 900, 560
FRAMED = Rect(60, 120, 420, 220)

SCENES = {
    "selecting": (SessionState.SELECTING, FRAMED, "", 0),
    "adjusting": (SessionState.ADJUSTING, FRAMED, "", 0),
    # Below the minimum: the capsule must explain itself rather than the
    # session quietly dying.
    "adjusting-too-small": (SessionState.ADJUSTING, Rect(60, 120, 8, 8), "", 0),
    "processing": (SessionState.PROCESSING, FRAMED, "正在翻译 3/12 · CUDA", 37),
    "failed": (SessionState.FAILED, FRAMED, "处理失败（RuntimeError），请检查模型或重新启动", 0),
}


def backdrop() -> QImage:
    """A light-to-dark sweep, so chrome can be judged against both ends."""
    image = QImage(WIDTH, HEIGHT, QImage.Format.Format_RGB888)
    painter = QPainter(image)
    gradient = QLinearGradient(0, 0, WIDTH, 0)
    gradient.setColorAt(0.0, QColor("#F5F5F5"))
    gradient.setColorAt(0.5, QColor("#9A9A9A"))
    gradient.setColorAt(1.0, QColor("#101010"))
    painter.fillRect(image.rect(), gradient)
    painter.setPen(QColor("#303030"))
    painter.setFont(QFont("Arial", 18))
    for row in range(5):
        painter.drawText(60, 160 + row * 40, "The quick brown fox jumps over the lazy dog")
    painter.end()
    return image


def scene_model(state: SessionState, selection: Rect, message: str, elapsed: int):
    picker = SelectionModel()
    picker.adopt(selection)
    adjustable = state in (SessionState.SELECTING, SessionState.ADJUSTING)
    model = OverlayViewModel(
        state=state,
        message=message,
        selection=picker.rect,
        handles=picker.handles() if adjustable else (),
        commands=allowed_commands(state, picker),
        language_pair="英语 → 简体中文",
        elapsed_seconds=elapsed,
        cursor=(300, 250),
    )
    return replace(model, hint=default_hint(model))


def render(model, screen) -> QImage:
    controller = SimpleNamespace(
        overlay_model=lambda: model,
        handle=lambda *_args, **_kwargs: True,
        cursor_point=None,
        repaint=lambda: None,
        show_result_menu=lambda *_args: None,
    )
    overlay = Overlay(controller, screen)
    try:
        overlay.resize(WIDTH, HEIGHT)
        return overlay.grab().toImage()
    finally:
        overlay.close()


def main() -> int:
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else PROJECT_ROOT / "artifacts" / "ui"
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "msyh.ttc"
    if font_path.exists():
        QFontDatabase.addApplicationFont(str(font_path))
    app.setFont(QFont("Microsoft YaHei UI", 10))

    screen = ScreenShot(QRect(0, 0, WIDTH, HEIGHT), backdrop(), 1)
    for name, scene in SCENES.items():
        target = output / f"overlay-{name}.png"
        if not render(scene_model(*scene), screen).save(str(target)):
            raise RuntimeError(f"无法写入预览图：{target}")
        print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
