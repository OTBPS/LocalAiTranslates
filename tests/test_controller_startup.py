"""Controller construction and shutdown, which nothing covered before.

Start-up wires the configuration store, the backend, the tray, the shortcut,
the readiness timer and the host service in one constructor. That sequence had
no test at all, so a wiring mistake could only be found by launching the
application -- which is impossible while another copy holds the single-instance
lock.
"""

import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QWidget

from screen_translator.config_store import ConfigStore
from screen_translator.controller import Controller
from screen_translator.core import Config
from screen_translator.tasks import TaskRunner


@pytest.fixture(scope="module", autouse=True)
def qt_app():
    return QApplication.instance() or QApplication([])


class FakeHotkeys:
    def __init__(self, app, callback, **_kwargs):
        self.current = ""
        self.closed = False

    def apply(self, sequence):
        self.current = sequence

    def close(self):
        self.closed = True


class FakeBackend:
    kind = "local"

    def __init__(self):
        self.stopped = False
        self.ocr = SimpleNamespace(mode="未加载", warmup=Mock())
        self.translator = SimpleNamespace(mode="未加载", stop=Mock())

    def ready(self):
        return False

    def refresh(self):
        pass

    def describe(self):
        return "本地模型未下载"

    def stop(self):
        self.stopped = True


class FakeSettings(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.refreshed = 0
        self.shown_pairs = []

    def refresh(self):
        self.refreshed += 1

    def load_config(self):
        pass

    def show_language_pair(self, source, target):
        self.shown_pairs.append((source, target))

    def confirm_exit(self):
        pass


@pytest.fixture
def controller(tmp_path, monkeypatch):
    # Never touch the real configuration file or the real registry.
    store = ConfigStore(Config(model_dir=str(tmp_path)), writer=lambda _config: None)
    monkeypatch.setattr(
        "screen_translator.controller.ConfigStore", lambda **_kwargs: store
    )
    monkeypatch.setattr(QTimer, "singleShot", lambda _delay, _callback: None)
    backend = FakeBackend()
    subject = Controller(
        QApplication.instance(),
        FakeSettings,
        backend_factory=lambda _config: backend,
        hotkey_factory=FakeHotkeys,
        task_runner=TaskRunner(),
        show_settings_when_models_missing=False,
    )
    yield subject, backend, store
    if not backend.stopped:
        subject.quit()


def test_startup_wires_configuration_backend_and_shortcut(controller):
    subject, backend, store = controller

    assert subject.config is store.current
    assert subject.backend is backend
    assert subject.ocr is backend.ocr
    assert subject.translator is backend.translator
    assert subject.hotkey.current == store.current.hotkey
    assert subject.readiness_timer.isActive()


def test_configuration_changes_reach_the_settings_window(controller):
    subject, _backend, store = controller

    store.update(source_language="ja", target_language="en")

    # The window is told the new pair instead of being reloaded wholesale,
    # which is what used to discard unsaved edits.
    assert subject.settings.shown_pairs[-1] == ("ja", "en")


def test_swapping_languages_does_not_reload_the_whole_form(controller):
    subject, _backend, store = controller
    store.update(source_language="en", target_language="zh-Hans")
    subject.settings.load_config = Mock()

    subject.swap_languages()

    assert (store.current.source_language, store.current.target_language) == (
        "zh-Hans",
        "en",
    )
    subject.settings.load_config.assert_not_called()


def test_quit_stops_the_timer_the_shortcut_and_the_backend(controller):
    subject, backend, _store = controller
    subject.app = SimpleNamespace(quit=Mock())

    subject.quit()

    assert subject.readiness_timer.isActive() is False
    assert subject.hotkey.closed is True
    assert backend.stopped is True
