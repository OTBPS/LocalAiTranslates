"""The shared controls, and the theme contract they are built against.

The direction test at the bottom is inverted rather than deleted when
the visual flip lands; ADR 0002 explains why a superseded guard is still
worth keeping as a guard.
"""

import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import pytest
from PySide6.QtWidgets import QApplication, QComboBox, QLineEdit, QPushButton

from screen_translator.design import metrics, semantic
from screen_translator.theme import application_stylesheet, create_app_icon
from screen_translator.widgets import (
    AppHeader,
    Card,
    Field,
    InsetGroup,
    LanguageRow,
    StatusChip,
    ToggleSwitch,
    icon_button,
    primary_button,
)


@pytest.fixture(scope="module", autouse=True)
def qt_app():
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(application_stylesheet())
    return app


def test_toggle_switch_meets_target_size_and_tracks_state(monkeypatch):
    monkeypatch.setattr("screen_translator.widgets.toggle.animations_enabled", lambda: False)
    switch = ToggleSwitch()

    assert switch.height() >= metrics.ACTIVE.height_control
    assert not switch.isChecked()
    switch.setChecked(True)

    # Correct before the first paint: an animation that has not run is
    # not a reason to draw the wrong state.
    assert switch.isChecked()
    assert switch.position == 1.0


def test_the_switch_takes_its_colours_from_the_tokens():
    from screen_translator.design import components

    tokens = components.toggle(semantic.ACTIVE, metrics.ACTIVE)

    # Six colours used to be written into paintEvent because QSS cannot
    # reach a widget that paints itself. The function is what lets the
    # switch and the stylesheet read the same values.
    assert tokens.track_on == semantic.ACTIVE.accent_fill
    assert tokens.track_off == semantic.ACTIVE.bg_surface_raised


def test_a_field_binds_its_label_and_names_its_control():
    control = QLineEdit()

    field = Field("主机地址", control)

    # Accessibility by construction, not by each call site remembering.
    assert field.label.buddy() is control
    assert control.accessibleName() == "主机地址"


def test_a_field_keeps_a_name_the_caller_set_deliberately():
    control = QComboBox()
    control.setAccessibleName("翻译模型（下载用）")

    field = Field("翻译模型", control)

    assert control.accessibleName() == "翻译模型（下载用）"
    assert field.label.text() == "翻译模型"


def test_an_icon_button_cannot_be_built_without_an_accessible_name():
    with pytest.raises(TypeError):
        icon_button("swap.svg")  # type: ignore[call-arg]

    control = icon_button("swap.svg", "对调输入和输出语言")
    assert control.accessibleName() == "对调输入和输出语言"
    # The tooltip defaults to the name: an icon-only control has to be
    # reachable by pointer as well as by screen reader.
    assert control.toolTip() == "对调输入和输出语言"


def test_buttons_are_plain_push_buttons_not_subclasses():
    # Several assertions elsewhere sweep findChildren(QPushButton); a
    # subclass would keep working there right up until it did not.
    assert type(primary_button("开始截图")) is QPushButton
    assert primary_button("开始截图").objectName() == "primaryButton"


def test_an_inset_group_separates_its_rows_with_hairlines():
    from screen_translator.widgets import Divider

    group = InsetGroup()
    group.add_row(QPushButton("一"))
    group.add_row(QPushButton("二"))
    group.add_row(QPushButton("三"))

    assert len(group.rows) == 3
    # Two separators for three rows -- not a trailing one, which is the
    # detail hand-built versions always get wrong.
    assert len(group.findChildren(Divider)) == 2


def test_a_card_accepts_both_widgets_and_layouts():
    from PySide6.QtWidgets import QHBoxLayout

    card = Card("语言", "选择输入与输出")
    card.add(QPushButton("按钮"))
    card.add(QHBoxLayout())

    assert card.body.count() >= 4


@pytest.mark.parametrize("width", [300, 680, 820])
def test_the_header_fits_every_width_it_can_be_given(width):
    header = AppHeader("屏译", "把屏幕上的文字翻译过来")
    header.resize(width, 80)
    header.show()
    try:
        # The painted banner placed a circle at width() - 108, which ran
        # off the edge below that width and at high DPI. Typography has
        # no such failure mode, and this is the check that says so.
        assert header.grab().width() == width
        assert header.title.x() >= 0 and header.title.width() <= width
        assert not header.subtitle.isHidden()
    finally:
        header.close()


def test_the_header_hides_a_subtitle_it_was_not_given():
    header = AppHeader("屏译")

    assert header.subtitle.isHidden()


def test_a_status_chip_always_carries_text_beside_its_colour():
    chip = StatusChip("模型未下载", "warning")

    assert chip.text() == "模型未下载"
    assert chip.role == "warning"
    chip.show_state("就绪", "success")
    assert chip.text() == "就绪" and chip.role == "success"


def test_an_unknown_chip_role_falls_back_rather_than_raising():
    assert StatusChip("状态", "chartreuse").role == "neutral"


def test_the_language_row_exposes_its_parts_by_name():
    from screen_translator.core import LANGUAGE_NAMES, SOURCE_LANGUAGES, TARGET_LANGUAGES

    row = LanguageRow(SOURCE_LANGUAGES, TARGET_LANGUAGES, LANGUAGE_NAMES)

    assert row.source.count() == len(SOURCE_LANGUAGES)
    assert row.target.count() == len(TARGET_LANGUAGES)
    assert row.swap.accessibleName()
    assert row.selection() == (row.source.currentData(), row.target.currentData())


def test_the_application_icon_still_covers_every_windows_size():
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


def test_the_theme_contract_matches_the_direction_currently_shipping():
    """Inverted, not deleted, when the visual flip lands. See ADR 0002.

    At that point this asserts that system blue is present and the
    constructivist red is absent from chrome — the same guard, pointed
    the other way.
    """
    stylesheet = application_stylesheet()
    theme = semantic.ACTIVE

    assert theme.accent_fill in stylesheet
    assert theme.bg_hover in stylesheet
    for stray in ("#007AFF", "#0066DB"):
        assert stray not in stylesheet, "the flip has landed; invert this test"
