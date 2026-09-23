import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from screen_translator.core import Config, TranslatedBlock
from screen_translator.feedback import Occupancy
from screen_translator.inference import InferenceCoordinator
from screen_translator.manual_translation import ManualTranslationController
from screen_translator.text_translation_page import (
    CANCELLED_STATUS,
    COPIED_STATUS,
    PREEMPTED_STATUS,
    READY_STATUS,
    TextTranslationPage,
)


def qt_app():
    return QApplication.instance() or QApplication([])


class FakePort:
    def __init__(self, behaviour=None):
        self.mode = "CUDA"
        self.model = SimpleNamespace(model_id="qwen3-8b-q5-k-m")
        self.adapter_id = None
        self.behaviour = behaviour
        self.calls = []

    def start(self, token, progress):
        pass

    def stop(self):
        pass

    def translate(self, blocks, token, progress, source_language="auto", target_language="zh-Hans",
                  detected_language=None):
        self.calls.append((source_language, target_language))
        if self.behaviour is not None:
            return self.behaviour(blocks, token, progress)
        return [TranslatedBlock(block, f"译{block.text}") for block in blocks]


class SyncRunner:
    def start(self, target, *, name):
        target()


class DeferredRunner:
    def __init__(self):
        self.pending = []

    def start(self, target, *, name):
        self.pending.append(target)

    def run_all(self):
        pending, self.pending = self.pending, []
        for target in pending:
            target()


def build(port=None, runner=None, **overrides):
    qt_app()
    port = port or FakePort()
    arbiter = InferenceCoordinator(lambda: port)
    manual = ManualTranslationController(arbiter, runner or SyncRunner())
    controller = SimpleNamespace(
        config=Config(translation_model="qwen3-8b-q5-k-m", source_language="en", target_language="zh-Hans"),
        busy=False,
        detected_source_language=None,
        translator=port,
        backend=SimpleNamespace(ready=lambda: True, describe=lambda: "本地模型就绪"),
        manual=manual,
        inference=arbiter,
        set_language_pair=Mock(return_value=True),
    )
    # Mirrors the real predicate: one question, answered in one place.
    controller.occupancy = lambda: Occupancy(bool(controller.busy), "截图翻译正在进行")
    controller.__dict__.update(overrides)
    return TextTranslationPage(controller), controller, port, arbiter


def test_page_starts_empty_and_disabled():
    page, _controller, _port, _arbiter = build()

    assert page.source_text.toPlainText() == ""
    assert page.target_text.toPlainText() == ""
    assert page.translate_button.isEnabled() is False
    assert page.cancel_button.isEnabled() is False
    assert page.copy_button.isEnabled() is False
    assert READY_STATUS in page.status.text()
    page.deleteLater()


def test_typing_enables_translation_and_the_result_is_rendered():
    page, _controller, port, _arbiter = build()

    page.source_text.setPlainText("1. Alpha\n2. Beta\n")
    assert page.translate_button.isEnabled() is True

    page.translate_button.click()

    assert page.target_text.toPlainText() == "1. 译Alpha\n2. 译Beta\n"
    assert port.calls == [("en", "zh-Hans")]
    assert page.target_text.isReadOnly() is True
    assert page.copy_button.isEnabled() is True
    page.deleteLater()


def test_translation_runs_without_blocking_the_input_field():
    runner = DeferredRunner()
    page, _controller, _port, _arbiter = build(runner=runner)
    page.source_text.setPlainText("Hello")

    page.translate_button.click()

    assert page.cancel_button.isEnabled() is True
    assert page.translate_button.isEnabled() is False
    assert QApplication.instance() is not None  # the event loop was never blocked

    runner.run_all()

    assert page.target_text.toPlainText() == "译Hello"
    assert page.cancel_button.isEnabled() is False
    page.deleteLater()


def test_cancelling_a_queued_task_keeps_it_away_from_the_engine():
    runner = DeferredRunner()
    port = FakePort()
    page, _controller, _port, _arbiter = build(port, runner)
    page.source_text.setPlainText("Hello")
    page.translate_button.click()
    page.cancel_button.click()
    runner.run_all()

    assert port.calls == []
    assert CANCELLED_STATUS in page.status.text()
    assert page.target_text.toPlainText() == ""
    page.deleteLater()


def test_cancel_during_translation_is_reported_as_a_user_cancel():
    holder = {}

    def behaviour(blocks, token, progress):
        holder["page"].cancel_button.click()
        token.check()
        return []

    page, _controller, _port, _arbiter = build(FakePort(behaviour))
    holder["page"] = page
    page.source_text.setPlainText("Hello")

    page.translate_button.click()

    assert CANCELLED_STATUS in page.status.text()
    assert page.cancel_button.isEnabled() is False
    page.deleteLater()


def test_a_capture_preemption_is_reported_differently_from_a_user_cancel():
    holder = {}

    def behaviour(blocks, token, progress):
        holder["arbiter"].begin_capture()
        token.check()
        return []

    page, _controller, _port, arbiter = build(FakePort(behaviour))
    holder["arbiter"] = arbiter
    page.source_text.setPlainText("Hello")

    page.translate_button.click()

    assert PREEMPTED_STATUS in page.status.text()
    page.deleteLater()


def test_copy_places_the_translation_on_the_clipboard():
    page, _controller, _port, _arbiter = build()
    page.source_text.setPlainText("Hello")
    page.translate_button.click()

    page.copy_button.click()

    assert QGuiApplication.clipboard().text() == "译Hello"
    assert COPIED_STATUS in page.status.text()
    page.deleteLater()


def test_copy_is_a_no_op_without_a_translation():
    page, _controller, _port, _arbiter = build()
    QGuiApplication.clipboard().setText("unchanged")

    page.copy_translation()

    assert QGuiApplication.clipboard().text() == "unchanged"
    page.deleteLater()


def test_clear_empties_both_fields():
    page, _controller, _port, _arbiter = build()
    page.source_text.setPlainText("Hello")
    page.translate_button.click()

    page.clear_button.click()

    assert page.source_text.toPlainText() == ""
    assert page.target_text.toPlainText() == ""
    assert page.translate_button.isEnabled() is False
    assert page.clear_button.isEnabled() is False
    page.deleteLater()


def test_swapping_updates_both_combos_and_persists_the_pair():
    page, controller, _port, _arbiter = build()

    page.swap_button.click()

    assert page.source_language.currentData() == "zh-Hans"
    assert page.target_language.currentData() == "en"
    controller.set_language_pair.assert_called_with("zh-Hans", "en")
    page.deleteLater()


def test_swapping_is_disabled_for_an_undetected_automatic_source():
    page, _controller, _port, _arbiter = build()
    page.set_combo(page.source_language, "auto")
    page.refresh()

    assert page.swap_button.isEnabled() is False
    page.deleteLater()


@pytest.mark.parametrize(
    ("source", "target"),
    [("en", "zh-Hans"), ("ja", "zh-Hans"), ("ko", "zh-Hans"), ("zh-Hans", "ja"), ("zh-Hans", "ko")],
)
def test_every_language_direction_is_selectable_and_forwarded(source, target):
    page, _controller, port, _arbiter = build()
    page.source_language.blockSignals(True)
    page.target_language.blockSignals(True)
    page.set_combo(page.source_language, source)
    page.set_combo(page.target_language, target)
    page.source_language.blockSignals(False)
    page.target_language.blockSignals(False)

    page.source_text.setPlainText("文本 text")
    page.translate_button.click()

    assert port.calls == [(source, target)]
    page.deleteLater()


def test_controls_are_locked_while_a_capture_is_running():
    page, controller, _port, _arbiter = build()
    page.source_text.setPlainText("Hello")
    controller.busy = True

    page.refresh()

    assert page.translate_button.isEnabled() is False
    assert page.source_language.isEnabled() is False
    page.deleteLater()


def test_language_edits_are_ignored_while_a_capture_is_running():
    page, controller, _port, _arbiter = build()
    controller.busy = True

    page.set_combo(page.target_language, "ja")

    controller.set_language_pair.assert_not_called()
    assert page.target_language.currentData() == "zh-Hans"
    page.deleteLater()


def test_empty_input_is_reported_without_a_translation():
    page, _controller, port, _arbiter = build()
    page.source_text.setPlainText("   ")

    page.start_translation()

    assert port.calls == []
    assert page.target_text.toPlainText() == ""
    page.deleteLater()


def test_a_superseded_result_does_not_overwrite_the_newer_one():
    page, _controller, _port, _arbiter = build()
    page.translation_started(7)
    page.translation_finished(6, "stale")

    assert page.target_text.toPlainText() == ""

    page.translation_finished(7, "fresh")
    assert page.target_text.toPlainText() == "fresh"
    page.deleteLater()


def test_accessibility_names_and_tab_order_are_declared():
    page, _controller, _port, _arbiter = build()

    assert page.source_text.accessibleName() == "原文输入框"
    assert page.target_text.accessibleName() == "译文输出框"
    assert page.source_language.accessibleName() == "输入语言"
    assert page.target_language.accessibleName() == "输出语言"
    assert page.swap_button.accessibleName() == "对调输入和输出语言"
    assert page.source_text.tabChangesFocus() is True
    assert page.source_text.isReadOnly() is False
    page.deleteLater()


def test_status_shows_the_model_but_never_the_language_pair():
    page, _controller, _port, _arbiter = build()

    text = page.status.text()
    assert "Qwen3 8B（平衡）" in text and "CUDA" in text
    labels = {label.text() for label in page.findChildren(QLabel)}
    assert "英语 → 简体中文" not in labels
    assert {"原文", "译文", "输入语言", "输出语言"} <= labels
    buttons = {button.text() for button in page.findChildren(QPushButton)}
    assert {"翻译", "取消", "复制译文", "清空"} <= buttons
    page.deleteLater()
