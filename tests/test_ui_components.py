import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from screen_translator.theme import application_stylesheet, create_app_icon
from screen_translator.ui_components import ConstructivistHero, ToggleSwitch


def qt_app():
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(application_stylesheet())
    return app


def test_toggle_switch_meets_target_size_and_tracks_state(monkeypatch):
    qt_app()
    monkeypatch.setattr("screen_translator.ui_components.animations_enabled", lambda: False)
    switch = ToggleSwitch()
    assert switch.width() >= 44
    assert switch.height() >= 44
    assert not switch.isChecked()
    switch.setChecked(True)
    assert switch.isChecked()
    assert switch.position == 1.0
    assert switch.accessibleName() == ""


def test_constructivist_theme_assets_render_offscreen():
    qt_app()
    hero = ConstructivistHero()
    hero.resize(640, 96)
    hero.show()
    QApplication.processEvents()
    assert not hero.grab().isNull()
    icon = create_app_icon()
    assert not icon.isNull()
    assert {(size.width(), size.height()) for size in icon.availableSizes()} == {
        (16, 16),
        (20, 20),
        (24, 24),
        (32, 32),
        (40, 40),
        (48, 48),
        (64, 64),
        (128, 128),
        (256, 256),
    }


def test_constructivist_theme_contract_avoids_legacy_ios_chrome():
    stylesheet = application_stylesheet()
    assert "#C51D23" in stylesheet
    assert "#E8BC35" in stylesheet
    assert "#007AFF" not in stylesheet
    assert "border-radius: 6px" not in stylesheet
