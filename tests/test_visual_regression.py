"""Visual regression by colour census, not by pixel diff.

Pixel baselines do not survive travelling between machines: offscreen
text rendering depends on the installed `msyh.ttc`, the Qt build and the
ClearType setting, so a baseline produces false failures, gets bypassed,
and then protects nothing.

Which colours occupy large areas is stable across all of that. Font
rendering changes how pixels are distributed; it does not invent a colour
the theme does not contain. So the assertion is: **every dominant colour
in a rendered window is one the theme declares.** That catches a stray
literal, an un-themed widget and a wrong state colour, which is most of
what actually goes wrong.
"""

from __future__ import annotations

import os
from collections import Counter

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from screen_translator.design import metrics, semantic, typography
from screen_translator.design.qss import stylesheet
from screen_translator.settings import Settings

#: A colour below this share of the window is antialiasing, not design.
DOMINANT_SHARE = 0.002
#: Sampling every other pixel is four times faster and does not change
#: which colours are dominant.
STEP = 2


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    return app


def census(image) -> dict[str, float]:
    counts: Counter[str] = Counter()
    for y in range(0, image.height(), STEP):
        for x in range(0, image.width(), STEP):
            colour = image.pixelColor(x, y)
            counts[f"#{colour.red():02X}{colour.green():02X}{colour.blue():02X}"] += 1
    total = sum(counts.values()) or 1
    return {
        colour: count / total
        for colour, count in counts.items()
        if count / total >= DOMINANT_SHARE
    }


def window(qt_app, theme, sizes, tmp_path):
    from scripts.render_ui_preview import PreviewController

    qt_app.setStyleSheet(stylesheet(theme, sizes, typography.ACTIVE))
    view = Settings(PreviewController(tmp_path))
    view.resize(820, 840)
    return view


SCENES = [
    pytest.param(820, 840, 0, id="capture-default"),
    pytest.param(820, 840, 1, id="text-default"),
    pytest.param(820, 840, 2, id="system-default"),
    # The declared minimum. Everything has to fit or scroll, and nothing
    # new may appear in the palette because a card got narrower.
    pytest.param(680, 600, 2, id="system-minimum"),
]


#: States that only appear once something has gone wrong or is in
#: progress, and so bring colours the default scenes never render.
STATES = [
    pytest.param("error", id="error-banner"),
    pytest.param("progress", id="downloading"),
]


def enter_state(view, state: str) -> None:
    from screen_translator.downloads import DownloadSnapshot
    from screen_translator.feedback import error_notice

    if state == "error":
        view.notify(
            error_notice(
                "scene", "无法连接到主机", detail="主机未响应，请确认它已开机", context="remote"
            )
        )
    elif state == "progress":
        from screen_translator.download_session import DownloadState

        view.show_download(
            DownloadSnapshot(
                state=DownloadState.DOWNLOADING,
                model_id="qwen3-8b-q5-k-m",
                file_name="Qwen3-8B-Q5_K_M.gguf",
                fraction=0.53,
                detail="正在下载 3.1/5.8 GB",
                cancellable=True,
            )
        )


@pytest.mark.parametrize("state", STATES)
def test_a_reported_state_introduces_no_colour_of_its_own(qt_app, tmp_path, state):
    theme = semantic.ACTIVE
    view = window(qt_app, theme, metrics.ACTIVE, tmp_path)
    try:
        view.show()
        view.tabs.setCurrentIndex(2)
        enter_state(view, state)
        qt_app.processEvents()

        found = census(view.grab().toImage())
        declared = {value.upper() for value in theme.values()}
        strays = {
            colour: round(share * 100, 3)
            for colour, share in found.items()
            if colour not in declared
        }

        assert not strays, f"{state} introduced {strays}"
    finally:
        view.close()


@pytest.mark.parametrize(("width", "height", "tab"), SCENES)
def test_every_dominant_colour_belongs_to_the_theme(qt_app, tmp_path, width, height, tab):
    theme = semantic.ACTIVE
    view = window(qt_app, theme, metrics.ACTIVE, tmp_path)
    try:
        view.resize(width, height)
        view.tabs.setCurrentIndex(tab)
        qt_app.processEvents()

        found = census(view.grab().toImage())
        declared = {value.upper() for value in theme.values()}
        strays = {
            colour: round(share * 100, 3)
            for colour, share in found.items()
            if colour not in declared
        }

        assert not strays, f"colours no theme declares: {strays}"
    finally:
        view.close()


def test_the_census_would_notice_a_stray_colour(qt_app, tmp_path):
    """The test above is only worth having if it can fail."""
    view = window(qt_app, semantic.ACTIVE, metrics.ACTIVE, tmp_path)
    try:
        view.setStyleSheet("QWidget { background: #FF00FF; }")
        qt_app.processEvents()

        found = census(view.grab().toImage())

        assert "#FF00FF" in found
        assert "#FF00FF" not in {value.upper() for value in semantic.ACTIVE.values()}
    finally:
        view.close()
        qt_app.setStyleSheet(stylesheet(semantic.ACTIVE, metrics.ACTIVE, typography.ACTIVE))


@pytest.mark.parametrize(("width", "height", "tab"), SCENES)
def test_nothing_overflows_the_window(qt_app, tmp_path, width, height, tab):
    """Structural check: the minimum size has to hold or scroll."""
    view = window(qt_app, semantic.ACTIVE, metrics.ACTIVE, tmp_path)
    try:
        view.resize(width, height)
        view.tabs.setCurrentIndex(tab)
        qt_app.processEvents()

        # A horizontal scrollbar means something is genuinely too wide;
        # vertical scrolling is the declared reflow strategy.
        assert view.scroll.horizontalScrollBar().maximum() == 0
        for child in view.findChildren(type(view.tabs)):
            assert child.width() <= width, f"{child.objectName()} is wider than the window"
    finally:
        view.close()


def test_each_tab_scrolls_on_its_own(qt_app, tmp_path):
    """One scroll area around everything let the longest page rule.

    `QTabWidget.minimumSizeHint` is the maximum over its pages, so a
    single outer scroll area gave every tab the system page's minimum
    -- 819 px. The text page needs 525 and was stretched to 808, which
    pushed its Translate button below the fold at the *default* window
    size, not merely the smallest one.
    """
    view = window(qt_app, semantic.ACTIVE, metrics.ACTIVE, tmp_path)
    try:
        view.resize(820, 840)
        view.show()
        lengths = {}
        for tab in range(view.tabs.count()):
            view.tabs.setCurrentIndex(tab)
            qt_app.processEvents()
            lengths[tab] = view.scroll.verticalScrollBar().maximum()

        # The system page is genuinely long and must scroll; the other
        # two must not inherit that.
        assert lengths[0] == 0, f"the capture page should fit: {lengths}"
        assert lengths[1] == 0, f"the text page should fit: {lengths}"
        assert lengths[2] > 0, "the system page is long enough to scroll"
    finally:
        view.close()


def test_the_primary_action_of_each_page_is_reachable_without_scrolling(qt_app, tmp_path):
    """At the default window size. The minimum size may scroll; the
    default is what a user actually opens."""
    view = window(qt_app, semantic.ACTIVE, metrics.ACTIVE, tmp_path)
    try:
        view.resize(820, 840)
        view.show()
        view.tabs.setCurrentIndex(1)
        qt_app.processEvents()

        button = view.text_page.translate_button
        viewport = view.scroll.viewport()
        bottom = button.mapTo(viewport, button.rect().bottomRight()).y()

        assert bottom <= viewport.height(), (
            f"Translate ends at {bottom} in a {viewport.height()}px viewport"
        )
    finally:
        view.close()


def test_the_banner_and_header_do_not_scroll_away(qt_app, tmp_path):
    """The banner reports on a footer button shared by every tab.

    It sits outside the tabs so a confirmation is visible from all of
    them; putting it inside a scroll area would let it leave the screen
    instead, which is the same bug in a new place.
    """
    view = window(qt_app, semantic.ACTIVE, metrics.ACTIVE, tmp_path)
    try:
        for scroll in view._scrolls:
            assert not scroll.isAncestorOf(view.banner)
            assert not scroll.isAncestorOf(view.header)
            assert not scroll.isAncestorOf(view.tabs)
    finally:
        view.close()


def test_every_focusable_control_has_an_accessible_name(qt_app, tmp_path):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QComboBox, QLineEdit, QPushButton

    view = window(qt_app, semantic.ACTIVE, metrics.ACTIVE, tmp_path)
    try:
        missing = []
        for kind in (QPushButton, QComboBox, QLineEdit):
            for widget in view.findChildren(kind):
                if widget.focusPolicy() == Qt.FocusPolicy.NoFocus:
                    continue
                # A button's own label is its name; anything else needs
                # one set, or a screen reader announces nothing.
                label = widget.accessibleName() or getattr(widget, "text", lambda: "")()
                if not label:
                    missing.append(f"{kind.__name__}#{widget.objectName()}")
        assert not missing, missing
    finally:
        view.close()
