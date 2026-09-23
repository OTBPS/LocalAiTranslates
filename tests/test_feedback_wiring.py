"""The two reporting failures the notice layer exists to fix.

Both were invisible to the test suite because each channel was correct in
isolation; what was wrong was which channel a given message went to.
"""

import os
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from screen_translator.config_store import ConfigStore
from screen_translator.controller import Controller
from screen_translator.core import Config
from screen_translator.feedback import NoticeCenter, Occupancy, Surface
from screen_translator.settings import Settings


@pytest.fixture(scope="module", autouse=True)
def qt_app():
    return QApplication.instance() or QApplication([])


@contextmanager
def _no_rollback_needed(_sequence):
    """Shortcut registration is covered by its own tests."""
    yield


class DeadTray:
    """A tray whose balloons never reach anyone, as Focus Assist can arrange."""

    surface = Surface.TRAY

    def __init__(self):
        self.presented = []

    def available(self):
        return True

    def present(self, notice):
        self.presented.append(notice)

    def revoke(self, notice_id):
        pass


@pytest.fixture
def window(tmp_path, monkeypatch):
    monkeypatch.setattr("screen_translator.settings.models_ready", lambda *_args: True)
    store = ConfigStore(Config(model_dir=str(tmp_path)), writer=lambda _config: None)
    controller = SimpleNamespace(
        configuration=store,
        config=store.current,
        busy=False,
        occupancy=lambda: Occupancy(),
        downloads=SimpleNamespace(
            active=False, cancel=Mock(), start=Mock(), redownload=Mock(return_value=None)
        ),
        detected_source_language=None,
        ocr=SimpleNamespace(mode="CUDA"),
        translator=SimpleNamespace(mode="CUDA"),
        backend=SimpleNamespace(kind="local", ready=lambda: True, describe=lambda: "就绪"),
        host_service=SimpleNamespace(status=SimpleNamespace(describe=lambda: "未启用")),
        hotkey=SimpleNamespace(current="Ctrl+Alt+T", pending=_no_rollback_needed),
        language_pair_text=lambda: "自动识别 → 简体中文",
        set_language_pair=Mock(return_value=True),
        refresh_language_actions=Mock(),
        replace_engines=Mock(),
        apply_host_service=Mock(),
        manual=None,
        toggle=Mock(),
    )
    view = Settings(controller)
    center = NoticeCenter()
    view.register_notice_sinks(center)
    yield view, controller, center
    view.close()


def test_the_save_confirmation_is_visible_from_every_tab(window, monkeypatch):
    view, _controller, _center = window
    monkeypatch.setattr("screen_translator.settings.set_startup", lambda _enabled: None)
    view.show()  # Save is pressed in a window the user is looking at.

    for tab in range(view.tabs.count()):
        view.tabs.setCurrentIndex(tab)
        view.banner.clear()

        assert view.apply() is True

        # The old confirmation went into a label inside the model card, which
        # only exists on the system settings tab; on the other two the user
        # pressed Save and saw nothing at all.
        assert view.banner.notice is not None, f"no confirmation on tab {tab}"
        assert view.banner.notice.notice_id == "settings-saved"
        assert view.banner.isHidden() is False


def test_the_banner_is_outside_the_tabs_it_reports_for(window):
    view, _controller, _center = window

    # Structural guarantee behind the test above: a message about a shared
    # footer button cannot live inside one of the pages.
    assert view.banner.parent() is not view.tabs
    assert view.tabs.isAncestorOf(view.banner) is False


def test_a_capture_failure_survives_a_tray_nobody_sees(window):
    view, controller, center = window
    tray = DeadTray()
    center.register_sink(tray)
    controller.notices = center
    controller.settings = view
    controller.session = SimpleNamespace(
        is_current=lambda _generation: True,
        finish_cancel=Mock(),
        transition=Mock(),
    )
    controller.cancel = Mock()
    controller.inference = SimpleNamespace(end_capture=Mock())
    controller.overlays = []

    # The window is hidden during a capture, so at this moment the only
    # surface is the tray -- the one Windows can silence.
    Controller.failed(controller, 1, "处理失败（RuntimeError）")

    assert [item.notice_id for item in tray.presented] == ["capture-failed"]
    assert view.banner.notice is None

    view.show()

    # Opening the window replays it, so a suppressed balloon is no longer
    # the difference between seeing the failure and never knowing about it.
    assert view.banner.notice is not None
    assert view.banner.notice.notice_id == "capture-failed"
    assert view.banner.notice.persistent, "the selection is already gone; the error must not be"
    assert [item.notice_id for item in center.history()] == ["capture-failed"]


def test_a_capture_failure_offers_the_retry_directly(window):
    view, controller, center = window
    controller.notices = center
    controller.settings = view
    controller.session = SimpleNamespace(
        is_current=lambda _generation: True, finish_cancel=Mock(), transition=Mock()
    )
    controller.cancel = Mock()
    controller.inference = SimpleNamespace(end_capture=Mock())
    controller.overlays = []
    Controller.failed(controller, 1, "处理失败")
    view.show()

    notice = view.banner.notice
    assert [action.action_id for action in notice.actions] == ["retry-capture"]

    Controller.on_notice_action(controller, "capture-failed", "retry-capture")

    controller.toggle.assert_called_once()
