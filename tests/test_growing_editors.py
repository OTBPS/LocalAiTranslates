"""The text boxes are as tall as their contents, not as tall as the page.

Reported from a screenshot: an empty translation page gave the input box
the entire window, so the box that held nothing was three screens tall
and the buttons that act on it were pushed out of sight. The old sizing
was a 104 px minimum plus a stretch factor, which is a guess that the
layout then inflated.

Assertions here are relationships -- taller than, equal to, capped at --
rather than pixel counts. Line height depends on the font actually
installed, so a pixel baseline would pass on this machine and fail on
the next one for no real reason.
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from screen_translator import design
from screen_translator.feedback.notices import Occupancy
from screen_translator.text_translation_page import (
    EDITOR_MAX_LINES,
    EDITOR_MIN_LINES,
    TextTranslationPage,
)
from screen_translator.widgets import GrowingTextEdit


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    design.apply(app)
    return app


def editor(minimum=3, maximum=14):
    box = GrowingTextEdit(minimum_lines=minimum, maximum_lines=maximum)
    box.resize(400, 100)
    return box


def lines(count):
    return "\n".join(f"line {index}" for index in range(count))


# --- the box itself ----------------------------------------------------


def test_an_empty_box_is_the_minimum_and_no_more(qt_app):
    """The complaint, stated as an assertion."""
    box = editor(minimum=3)

    assert box.lines_shown() == 3
    assert box.sizeHint().height() == box.minimumSizeHint().height()


def test_one_line_of_text_does_not_shrink_it_below_the_minimum(qt_app):
    box = editor(minimum=3)
    box.setPlainText("Hello")

    assert box.lines_shown() == 3


def test_the_box_grows_with_what_is_typed(qt_app):
    box = editor(minimum=3, maximum=14)
    empty = box.sizeHint().height()

    box.setPlainText(lines(6))

    assert box.lines_shown() == 6
    assert box.sizeHint().height() > empty


def test_growth_is_proportional_rather_than_a_single_step(qt_app):
    box = editor(minimum=3, maximum=20)
    heights = []
    for count in (4, 8, 12):
        box.setPlainText(lines(count))
        heights.append(box.sizeHint().height())

    assert heights == sorted(heights)
    assert len(set(heights)) == 3, "the box stopped responding to content"


def test_wrapped_lines_count_as_lines(qt_app):
    """What the reader sees is rows on screen, not newline characters."""
    box = editor(minimum=3, maximum=40)
    box.setPlainText("The quick brown fox jumps over the lazy dog. " * 10)
    box.show()
    qt_app.processEvents()

    assert box.document().blockCount() == 1, "this is one paragraph"
    assert box.lines_shown() > 3, "wrapping was not taken into account"
    box.hide()


def test_growth_stops_at_the_maximum(qt_app):
    box = editor(minimum=3, maximum=8)
    box.setPlainText(lines(40))

    assert box.lines_shown() == 8


def test_past_the_maximum_the_box_scrolls_instead(qt_app):
    """Capping is only acceptable if the rest is still reachable."""
    box = editor(minimum=3, maximum=8)
    box.setPlainText(lines(40))
    box.resize(box.width(), box.sizeHint().height())
    box.show()
    qt_app.processEvents()

    assert box.verticalScrollBar().maximum() > 0, "the overflow is unreachable"
    box.hide()


def test_the_height_follows_the_font_rather_than_a_pixel_constant(qt_app):
    """A pixel height is only correct at one font size and one scale.

    Sizes are set in pixels because the design system specifies them
    that way -- `pointSizeF()` reads back as -1 on a stylesheet font, so
    doubling it would silently do nothing and the test would pass
    without testing anything.
    """
    small = editor()
    large = editor()
    for box, pixels in ((small, 12), (large, 24)):
        font = QFont(box.font())
        font.setPixelSize(pixels)
        box.setFont(font)

    assert large.sizeHint().height() > small.sizeHint().height()
    # Three lines in both cases, so the whole difference is the font.
    assert large.lines_shown() == small.lines_shown()


def test_a_stretch_factor_cannot_take_the_box_back_over_the_page(qt_app):
    """The old sizing failed here: the policy let the layout inflate it."""
    host = QWidget()
    layout = QVBoxLayout(host)
    box = editor(minimum=3, maximum=14)
    layout.addWidget(box, 1)
    host.resize(400, 900)
    host.show()
    qt_app.processEvents()

    assert box.height() == pytest.approx(box.sizeHint().height(), abs=2), (
        "the box was stretched past the height it asked for"
    )
    host.hide()


def test_a_nonsense_range_does_not_invert(qt_app):
    box = editor(minimum=6, maximum=2)

    assert box.lines_shown() == 6


# --- the page that uses them ------------------------------------------


class StubController:
    def __init__(self):
        self.config = SimpleNamespace(
            translation_model="qwen3-8b", source_language="en", target_language="zh"
        )
        self.translator = SimpleNamespace(mode="已加载")
        self.backend = SimpleNamespace(ready=lambda: True, describe=lambda: "")
        self.detected_source_language = None
        self.set_language_pair = Mock()
        self.translate_text = Mock()
        self.cancel_text_translation = Mock()

    def occupancy(self):
        return Occupancy()


def test_an_empty_text_page_does_not_claim_the_whole_window(qt_app):
    """The regression this file exists for.

    The page used to want every pixel it was offered. Now it asks for
    roughly what it contains, so the buttons stay where they can be seen.
    """
    page = TextTranslationPage(StubController())
    page.resize(1040, 900)
    page.show()
    qt_app.processEvents()

    assert page.sizeHint().height() < 900, "the empty page still fills the window"
    assert page.source_text.lines_shown() == EDITOR_MIN_LINES
    assert page.target_text.lines_shown() == EDITOR_MIN_LINES
    page.hide()


def test_the_two_boxes_grow_independently(qt_app):
    page = TextTranslationPage(StubController())
    page.show()
    qt_app.processEvents()

    page.target_text.setPlainText(lines(8))

    assert page.target_text.lines_shown() == 8
    assert page.source_text.lines_shown() == EDITOR_MIN_LINES, (
        "the input box followed the output box"
    )
    page.hide()


def test_a_long_paste_cannot_push_the_buttons_off_the_page(qt_app):
    """Unbounded growth would be the original complaint with a new cause."""
    page = TextTranslationPage(StubController())
    page.show()
    qt_app.processEvents()

    page.source_text.setPlainText(lines(500))
    page.target_text.setPlainText(lines(500))
    qt_app.processEvents()

    assert page.source_text.lines_shown() == EDITOR_MAX_LINES
    assert page.target_text.lines_shown() == EDITOR_MAX_LINES
    page.hide()


def test_the_bounds_stay_in_a_sane_order():
    assert 0 < EDITOR_MIN_LINES < EDITOR_MAX_LINES
