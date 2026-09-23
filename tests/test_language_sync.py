"""Two pages show the language pair; they must not disagree.

The capture page and the text page each own a pair of combo boxes. They were
only ever refilled by a full `load_config()`, which ran when the window went
from hidden to visible. Changing the language on one page therefore left the
other showing the old value, and saving read the stale one and wrote it back
over the change the user had just made.
"""

import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from screen_translator.config_store import ConfigStore
from screen_translator.core import Config
from screen_translator.settings import Settings


@pytest.fixture(scope="module", autouse=True)
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setattr("screen_translator.settings.models_ready", lambda *_args: True)
    store = ConfigStore(
        Config(model_dir=str(tmp_path), source_language="en", target_language="zh-Hans"),
        writer=lambda _config: None,
    )
    controller = SimpleNamespace(
        configuration=store,
        config=store.current,
        busy=False,
        download_token=None,
        detected_source_language=None,
        ocr=SimpleNamespace(mode="CUDA"),
        translator=SimpleNamespace(mode="CUDA"),
        backend=SimpleNamespace(kind="local", ready=lambda: True, describe=lambda: "就绪"),
        host_service=SimpleNamespace(status=SimpleNamespace(describe=lambda: "未启用")),
        hotkey=SimpleNamespace(current="Ctrl+Alt+T"),
        language_pair_text=lambda: "英语 → 简体中文",
        set_language_pair=Mock(return_value=True),
        refresh_language_actions=Mock(),
        # The page skips its signal wiring when there is no controller, which
        # is all these tests need; language display is independent of it.
        manual=None,
        toggle=Mock(),
    )
    window = Settings(controller)
    yield window, controller, store
    window.close()


def pair(page):
    return page.source_language.currentData(), page.target_language.currentData()


def test_both_pages_start_on_the_stored_pair(settings):
    window, _controller, _store = settings

    assert pair(window) == ("en", "zh-Hans")
    assert pair(window.text_page) == ("en", "zh-Hans")


def test_a_stored_change_reaches_both_pages(settings):
    window, _controller, _store = settings

    window.show_language_pair("ja", "en")

    assert pair(window) == ("ja", "en")
    assert pair(window.text_page) == ("ja", "en")


def test_updating_the_display_does_not_re_emit_a_change(settings):
    window, controller, _store = settings
    controller.set_language_pair.reset_mock()

    window.show_language_pair("ko", "en")

    # Displaying a stored value must not look like the user editing it;
    # otherwise the two pages ping-pong updates at each other.
    controller.set_language_pair.assert_not_called()


def test_the_pages_cannot_drift_apart_and_overwrite_each_other(settings):
    window, _controller, store = settings

    # Simulate the text page being edited and the store accepting it.
    store.update(source_language="ja", target_language="en")
    window.show_language_pair(
        store.current.source_language, store.current.target_language
    )

    # The capture page, which `apply()` reads from, now agrees with the store.
    assert pair(window) == ("ja", "en")
    assert pair(window.text_page) == ("ja", "en")
