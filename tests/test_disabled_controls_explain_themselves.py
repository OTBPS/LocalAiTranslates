"""Greying a control out is only acceptable if the user can tell why.

MASTER.md draws the line at visibility, not at the act of disabling: a
copy button greyed beside an empty output box explains itself, and adding
a tooltip that says "the box is empty" would break the separate rule
against repeating an adjacent value. A capture running behind the window
explains nothing, so it has to be said.

This file holds the second kind. It exists because a sweep of the text
page found the language controls silently locked during a capture -- the
one state on that page the user genuinely cannot see.
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from screen_translator import design
from screen_translator.feedback.notices import Occupancy
from screen_translator.text_translation_page import TextTranslationPage

#: Frozen, so one shared instance is safe as a default.
UNBLOCKED = Occupancy()


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    design.apply(app)
    return app


class StubController:
    """Only what the page reads. A real controller drags in a tray icon."""

    def __init__(self, *, occupancy=UNBLOCKED, ready=True, describe="本地模型未下载"):
        self._occupancy = occupancy
        self._ready = ready
        self._describe = describe
        self.config = SimpleNamespace(
            translation_model="qwen3-8b",
            source_language="en",
            target_language="zh",
        )
        self.translator = SimpleNamespace(mode="已加载")
        self.backend = SimpleNamespace(
            ready=lambda: self._ready,
            describe=lambda: self._describe,
        )
        self.detected_source_language = None
        self.set_language_pair = Mock()
        self.translate_text = Mock()
        self.cancel_text_translation = Mock()

    def occupancy(self):
        return self._occupancy


def build(qt_app, **kwargs):
    page = TextTranslationPage(StubController(**kwargs))
    page.source_text.setPlainText("hello")
    page.refresh()
    return page


def blocked_controls(page):
    """Every control on the page that is currently disabled."""
    named = {
        "翻译": page.translate_button,
        "取消": page.cancel_button,
        "复制译文": page.copy_button,
        "清空": page.clear_button,
        "源语言": page.source_language,
        "目标语言": page.target_language,
        "对调": page.swap_button,
    }
    return {name: widget for name, widget in named.items() if not widget.isEnabled()}


# --- the states the user cannot see -----------------------------------


@pytest.mark.parametrize(
    ("label", "kwargs", "expected"),
    [
        (
            "截图进行中",
            {"occupancy": Occupancy(busy=True, reason="截图翻译正在进行")},
            "截图翻译正在进行",
        ),
        (
            "模型未下载",
            {"ready": False, "describe": "本地模型未下载"},
            "本地模型未下载",
        ),
    ],
)
def test_the_translate_button_names_an_invisible_blocker(qt_app, label, kwargs, expected):
    page = build(qt_app, **kwargs)

    assert not page.translate_button.isEnabled(), label
    assert page.translate_button.toolTip() == expected, label


def test_a_capture_locks_the_language_controls_and_says_so(qt_app):
    """The gap this file was written for.

    Nothing on this page shows that a capture is running elsewhere, so
    three controls used to grey out with no explanation at all.
    """
    page = build(qt_app, occupancy=Occupancy(busy=True, reason="截图翻译正在进行"))

    for name, widget in (
        ("源语言", page.source_language),
        ("目标语言", page.target_language),
        ("对调", page.swap_button),
    ):
        assert not widget.isEnabled(), name
        assert widget.toolTip() == "截图翻译正在进行", name


def test_every_control_blocked_by_a_capture_gives_the_same_reason(qt_app):
    """One cause should not produce several different explanations."""
    page = build(qt_app, occupancy=Occupancy(busy=True, reason="截图翻译正在进行"))

    reasons = {widget.toolTip() for widget in blocked_controls(page).values()}
    # 取消 is off because there is nothing running to cancel, which is
    # visible; everything blocked *by the capture* speaks with one voice.
    assert reasons <= {"截图翻译正在进行", ""}
    assert "截图翻译正在进行" in reasons


# --- the states the user can see --------------------------------------


def test_a_self_evident_state_does_not_narrate_itself(qt_app):
    """The other half of the rule, pinned so it is not "fixed" later.

    With an empty input and an empty output, four controls are off. Every
    one of them sits beside the empty box that explains it, and a tooltip
    here would be the forbidden pattern: copy that repeats an adjacent
    control's visible state.
    """
    page = TextTranslationPage(StubController())
    page.source_text.setPlainText("")
    page.refresh()

    off = blocked_controls(page)
    assert set(off) == {"翻译", "取消", "复制译文", "清空"}
    assert all(widget.toolTip() == "" for widget in off.values())


def test_the_explanation_is_taken_back_when_the_block_clears(qt_app):
    """A stale reason on a working control is worse than none."""
    page = build(qt_app, occupancy=Occupancy(busy=True, reason="截图翻译正在进行"))
    assert page.translate_button.toolTip() == "截图翻译正在进行"

    page.c._occupancy = Occupancy()
    page.refresh()

    assert page.translate_button.isEnabled()
    assert page.translate_button.toolTip() == "翻译（Ctrl+Enter）", (
        "the control's own tooltip did not come back"
    )
