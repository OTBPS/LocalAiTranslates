"""Following the system appearance, and what that needs besides a stylesheet.

A dark stylesheet on its own is not a dark application. `QMessageBox`,
`QToolTip`, spin-box arrows, the native file dialog and disabled text all
read the palette, and the project set no palette at all -- invisible
while everything was light, white-on-white the moment it was not.
"""

import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from screen_translator.design import metrics, semantic, typography
from screen_translator.design.primitives import contrast_ratio
from screen_translator.design.qpalette import palette
from screen_translator.design.qss import stylesheet
from screen_translator.settings import Settings


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


THEMES = [semantic.LIGHT, semantic.DARK]


@pytest.mark.parametrize("theme", THEMES, ids=lambda t: t.name)
def test_the_palette_covers_the_roles_a_stylesheet_cannot_reach(theme):
    result = palette(theme)

    for role, expected in (
        (QPalette.ColorRole.Window, theme.bg_canvas),
        (QPalette.ColorRole.Base, theme.bg_surface_raised),
        (QPalette.ColorRole.Text, theme.text_primary),
        (QPalette.ColorRole.ToolTipBase, theme.tooltip_bg),
        (QPalette.ColorRole.ToolTipText, theme.tooltip_text),
        (QPalette.ColorRole.Highlight, theme.accent_fill),
    ):
        assert result.color(role) == QColor(expected), role


@pytest.mark.parametrize("theme", THEMES, ids=lambda t: t.name)
def test_disabled_text_is_set_explicitly_rather_than_derived(theme):
    result = palette(theme)

    # Qt derives disabled text by lightening the enabled colour, which
    # on a dark background produces text lighter than the surface.
    disabled = result.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text)
    assert disabled == QColor(theme.text_disabled)
    assert disabled != result.color(QPalette.ColorRole.Text)


def test_the_tooltip_is_readable_in_both_themes():
    for theme in THEMES:
        assert contrast_ratio(theme.tooltip_text, theme.tooltip_bg) >= 4.5


def test_the_dark_theme_uses_the_dark_check_mark():
    # QSS references it through `image: url(...)`, which cannot be
    # recoloured at run time, so dark mode needs a second file rather
    # than a token. The light one keeps its name: `build_update.ps1`
    # uses `check.svg` as the incremental-package integrity sentinel.
    assert "check-dark.svg" in stylesheet(semantic.DARK, metrics.ROUNDED, typography.APPLE)
    assert "check-dark.svg" not in stylesheet(
        semantic.LIGHT, metrics.ROUNDED, typography.APPLE
    )


def test_the_window_renders_in_the_dark_theme(qt_app, tmp_path):
    """The census, pointed at the theme the application has never shipped."""
    from collections import Counter

    from scripts.render_ui_preview import PreviewController

    qt_app.setPalette(palette(semantic.DARK))
    qt_app.setStyleSheet(stylesheet(semantic.DARK, metrics.ROUNDED, typography.APPLE))
    view = Settings(PreviewController(tmp_path))
    try:
        view.resize(820, 840)
        view.show()
        qt_app.processEvents()
        image = view.grab().toImage()

        counts: Counter[str] = Counter()
        for y in range(0, image.height(), 2):
            for x in range(0, image.width(), 2):
                colour = image.pixelColor(x, y)
                counts[f"#{colour.red():02X}{colour.green():02X}{colour.blue():02X}"] += 1
        total = sum(counts.values()) or 1
        declared = {value.upper() for value in semantic.DARK.values()}
        strays = {
            colour: round(count / total * 100, 3)
            for colour, count in counts.items()
            if count / total >= 0.002 and colour not in declared
        }

        assert not strays, f"colours the dark theme does not declare: {strays}"
    finally:
        view.close()
        qt_app.setPalette(palette(semantic.ACTIVE))
        qt_app.setStyleSheet(stylesheet(semantic.ACTIVE, metrics.ACTIVE, typography.ACTIVE))


def test_the_system_appearance_is_read_from_the_per_application_setting(monkeypatch):
    import winreg

    from screen_translator.native import app_theme_is_light

    seen = {}

    class FakeKey:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def open_key(_root, path):
        seen["path"] = path
        return FakeKey()

    def query(_key, name):
        seen["name"] = name
        return 0, 4

    monkeypatch.setattr(winreg, "OpenKey", open_key)
    monkeypatch.setattr(winreg, "QueryValueEx", query)

    assert app_theme_is_light() is False
    # AppsUseLightTheme, not SystemUsesLightTheme: the two are separate
    # settings and users do set them differently.
    assert seen["name"] == "AppsUseLightTheme"
    assert "Themes\\Personalize" in seen["path"]


def test_a_missing_appearance_setting_falls_back_to_light(monkeypatch):
    import winreg

    from screen_translator.native import app_theme_is_light

    def missing(*_args, **_kwargs):
        raise OSError(2, "not found")

    monkeypatch.setattr(winreg, "OpenKey", missing)

    # Windows 10 before the setting existed.
    assert app_theme_is_light() is True


def test_the_window_material_is_harmless_where_it_is_unavailable(qt_app, monkeypatch):
    from screen_translator import native

    monkeypatch.setattr(native, "_set_window_attribute", lambda *_args: False)
    window = SimpleNamespace(winId=lambda: 1234, setAttribute=Mock())

    # Windows 10 and early 11 do not know the attribute. The expected
    # outcome is an opaque window, not an error.
    assert native.apply_window_material(window, dark=False) is False
    window.setAttribute.assert_not_called()


def test_the_title_bar_is_told_about_dark_mode_separately(qt_app, monkeypatch):
    from screen_translator import native

    calls = []
    monkeypatch.setattr(
        native,
        "_set_window_attribute",
        lambda handle, attribute, value: calls.append((attribute, value)) or True,
    )
    window = SimpleNamespace(winId=lambda: 1234, setAttribute=Mock())

    native.apply_window_material(window, dark=True)

    # Without this the title bar stays light above a dark window.
    assert (native._DWMWA_USE_IMMERSIVE_DARK_MODE, 1) in calls
    assert (native._DWMWA_SYSTEMBACKDROP_TYPE, native._DWMSBT_MAINWINDOW) in calls
