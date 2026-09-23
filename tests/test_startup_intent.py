"""The launch reason travels from the registry to the window decision.

Three pieces have to agree: the Run entry has to say that Windows started
the process, the argument parser has to recognise it, and the controller
has to act on it. Each was previously fine on its own and the chain did
not exist -- the application guessed from "are the models ready", so a
login on an unconfigured machine opened a window nobody asked for.
"""

import os
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QWidget

from screen_translator.config_store import ConfigStore
from screen_translator.controller import Controller
from screen_translator.core import Config
from screen_translator.navigation import Destination
from screen_translator.onboarding import Stage, StartupIntent
from screen_translator.tasks import TaskRunner


@pytest.fixture(scope="module", autouse=True)
def qt_app():
    return QApplication.instance() or QApplication([])


class FakeHotkeys:
    def __init__(self, app, callback, **_kwargs):
        self.current = ""

    def apply(self, sequence):
        self.current = sequence

    def close(self):
        pass


class FakeSettings(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.navigated = []
        self.shown = 0

    def refresh(self):
        pass

    def load_config(self):
        pass

    def navigate(self, destination, *, focus=True):
        self.navigated.append(destination)
        return True

    def showNormal(self):
        self.shown += 1

    def show_language_pair(self, source, target):
        pass

    def confirm_exit(self):
        pass


def controller_for(intent, *, ready=False, tmp_path=None, monkeypatch=None):
    store = ConfigStore(Config(model_dir=str(tmp_path)), writer=lambda _config: None)
    monkeypatch.setattr(
        "screen_translator.controller.ConfigStore", lambda **_kwargs: store
    )
    monkeypatch.setattr(QTimer, "singleShot", lambda _delay, _callback: None)
    monkeypatch.setattr(
        "screen_translator.controller.local_runtime_available", lambda: True
    )
    backend = SimpleNamespace(
        kind="local",
        ocr=SimpleNamespace(mode="未加载", warmup=Mock()),
        translator=SimpleNamespace(mode="未加载"),
        ready=lambda: ready,
        refresh=lambda: None,
        describe=lambda: "本地模型未下载",
        stop=lambda: None,
    )
    return Controller(
        QApplication.instance(),
        FakeSettings,
        backend_factory=lambda _config: backend,
        hotkey_factory=FakeHotkeys,
        task_runner=TaskRunner(),
        intent=intent,
    )


def test_a_login_launch_stays_in_the_tray_but_still_reports(tmp_path, monkeypatch):
    subject = controller_for(StartupIntent.AUTOSTART, tmp_path=tmp_path, monkeypatch=monkeypatch)
    try:
        plan = subject.review_onboarding(StartupIntent.AUTOSTART)

        assert plan.stage is Stage.NEEDS_MODEL
        assert subject.settings.shown == 0
        # Silent does not mean invisible: the tray message is still posted.
        assert [item.notice_id for item in subject.notices.active()] == ["onboarding"]
    finally:
        subject.app = SimpleNamespace(quit=Mock())
        subject.quit()


def test_a_user_launch_lands_on_the_control_that_fixes_it(tmp_path, monkeypatch):
    subject = controller_for(StartupIntent.LAUNCH, tmp_path=tmp_path, monkeypatch=monkeypatch)
    try:
        subject.review_onboarding(StartupIntent.LAUNCH)

        assert subject.settings.shown == 1
        assert subject.settings.navigated == [Destination.MODEL_DOWNLOAD]
    finally:
        subject.app = SimpleNamespace(quit=Mock())
        subject.quit()


def test_the_first_run_message_is_retracted_once_the_backend_works(tmp_path, monkeypatch):
    subject = controller_for(StartupIntent.LAUNCH, tmp_path=tmp_path, monkeypatch=monkeypatch)
    try:
        subject.review_onboarding(StartupIntent.AUTOSTART)
        assert subject.notices.active()

        subject.backends.backend.ready = lambda: True
        subject.review_onboarding(may_open=False)

        # The message was sticky, so nothing else would ever clear it.
        assert subject.notices.active() == ()
        assert subject.config.onboarding_completed is True
    finally:
        subject.app = SimpleNamespace(quit=Mock())
        subject.quit()


def test_the_action_on_the_first_run_message_opens_the_download(tmp_path, monkeypatch):
    subject = controller_for(StartupIntent.AUTOSTART, tmp_path=tmp_path, monkeypatch=monkeypatch)
    try:
        subject.review_onboarding(StartupIntent.AUTOSTART)

        subject.on_notice_action("onboarding", "fix-onboarding")

        assert subject.settings.navigated == [Destination.MODEL_DOWNLOAD]
    finally:
        subject.app = SimpleNamespace(quit=Mock())
        subject.quit()


@pytest.mark.skipif(sys.platform != "win32", reason="registry Run entry is Windows only")
def test_the_run_entry_says_that_windows_started_the_process(monkeypatch):
    import winreg

    from screen_translator.native import AUTOSTART_FLAG, set_startup

    written = {}

    class FakeKey:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(winreg, "CreateKey", lambda _root, _path: FakeKey())
    monkeypatch.setattr(
        winreg,
        "SetValueEx",
        lambda _key, name, _reserved, _type, value: written.update({name: value}),
    )

    set_startup(True)

    # Without this the process cannot tell a login from a double-click,
    # and has to guess.
    assert AUTOSTART_FLAG in written["ScreenTranslator"]
