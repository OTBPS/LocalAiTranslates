"""The preview script must keep working, because nothing else notices.

`render_ui_preview.py` is the only thing that builds the settings window
outside the running application, which makes it the visual-review tool and
also the first thing to rot: it broke when the window started reading
`backend` and `host_service`, and no test caught it.
"""

import os

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from screen_translator.settings import Settings


@pytest.fixture(scope="module", autouse=True)
def qt_app():
    return QApplication.instance() or QApplication([])


def test_the_preview_controller_satisfies_the_settings_window(tmp_path):
    from scripts.render_ui_preview import PreviewController

    window = Settings(PreviewController(tmp_path))
    try:
        # Construction alone is not enough: refresh() is what reads the
        # controller surface that drifted last time.
        window.refresh()
        window.load_config()
        assert window.tabs.count() == 3
    finally:
        window.close()


def test_the_preview_renders_every_tab(tmp_path):
    from scripts.render_ui_preview import PreviewController

    window = Settings(PreviewController(tmp_path))
    try:
        for index in range(window.tabs.count()):
            window.tabs.setCurrentIndex(index)
            image = window.grab()
            assert not image.isNull(), f"tab {index} rendered nothing"
            assert image.width() > 0 and image.height() > 0
    finally:
        window.close()


def test_the_preview_output_is_not_named_after_a_retired_design(tmp_path):
    from pathlib import Path

    source = Path(__file__).resolve().parents[1] / "scripts" / "render_ui_preview.py"

    assert "settings-ios18.png" not in source.read_text(encoding="utf-8")


def test_every_overlay_state_renders():
    from PySide6.QtCore import QRect

    from screen_translator.graphics import ScreenShot
    from scripts.render_overlay_preview import (
        HEIGHT,
        SCENES,
        WIDTH,
        backdrop,
        render,
        scene_model,
    )

    # The overlay only exists between a hotkey press and a result, so this
    # script is the only way to look at it -- and it would rot just as
    # quietly as the settings preview did.
    screen = ScreenShot(QRect(0, 0, WIDTH, HEIGHT), backdrop(), 1)
    for name, scene in SCENES.items():
        image = render(scene_model(*scene), screen)
        assert not image.isNull(), name
        assert (image.width(), image.height()) == (WIDTH, HEIGHT), name

