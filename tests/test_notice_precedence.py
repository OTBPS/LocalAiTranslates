"""The page banner holds one message, so arrival order must not decide it.

Found by driving the real controller through the sequence a silent
autostart produces: the settings window is never opened, a capture fails
and lands in the tray (which Windows may suppress), and when the user
finally opens the window the centre replays the failure into the banner --
and then the first-run warning, posted a moment later by the same show,
lands on top of it. The error was gone from every surface at once.

Nothing was wrong with either message. What was wrong is that a surface
with a single slot was being written by two independent paths with no rule
about which one wins.
"""

from __future__ import annotations

import os

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from screen_translator.feedback.center import NoticeCenter
from screen_translator.feedback.notices import (
    Lifetime,
    Notice,
    Severity,
    error_notice,
    outranks,
    progress_notice,
    success_notice,
)
from screen_translator.feedback.sinks import BannerSink, NoticeBanner


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def hosted_banner() -> tuple[QWidget, NoticeBanner]:
    """A banner inside a window, the way the settings page builds it.

    `BannerSink.available` asks the banner's *window*; a parentless banner
    is its own window and reports itself unavailable the moment it hides,
    which is nothing like the real arrangement.
    """
    host = QWidget()
    layout = QVBoxLayout(host)
    banner = NoticeBanner()
    layout.addWidget(banner)
    host.show()
    return host, banner


def sticky(notice_id: str, severity: Severity) -> Notice:
    return Notice(
        notice_id=notice_id,
        severity=severity,
        title=notice_id,
        lifetime=Lifetime.STICKY,
    )


# --- the rule, without any widgets -------------------------------------


def test_an_ambient_warning_cannot_cover_a_standing_error():
    assert not outranks(sticky("onboarding", Severity.WARNING), sticky("failed", Severity.ERROR))


def test_an_error_covers_a_standing_warning():
    assert outranks(sticky("failed", Severity.ERROR), sticky("onboarding", Severity.WARNING))


def test_an_update_to_the_same_message_always_lands():
    """Otherwise a retry of the same failure could not refresh its own text."""
    first = error_notice("failed", "第一次")
    second = error_notice("failed", "第二次")
    assert outranks(second, first)


def test_anything_may_replace_a_message_that_is_already_leaving():
    passing = success_notice("saved", "已保存")
    assert not passing.persistent
    assert outranks(sticky("onboarding", Severity.WARNING), passing)


def test_progress_takes_the_slot_because_the_user_just_started_it():
    assert outranks(progress_notice("download", "下载中", 0.1), sticky("failed", Severity.ERROR))


def test_a_warning_does_not_interrupt_a_running_download():
    running = progress_notice("download", "下载中", 0.4)
    assert running.persistent
    assert not outranks(sticky("onboarding", Severity.WARNING), running)


def test_a_failure_may_interrupt_a_running_download():
    assert outranks(sticky("failed", Severity.ERROR), progress_notice("download", "下载中", 0.4))


# --- the rule, through the widget that has the slot --------------------


def test_the_banner_keeps_the_error_when_the_warning_arrives_second(qt_app):
    banner = NoticeBanner()
    sink = BannerSink(banner)

    sink.present(error_notice("capture-failed", "截屏翻译失败"))
    sink.present(sticky("onboarding", Severity.WARNING))

    assert banner.notice is not None
    assert banner.notice.notice_id == "capture-failed"


def test_replay_order_no_longer_decides_what_is_on_screen(qt_app):
    """Both orders have to end in the same place, or the bug is still there."""
    for order in (("capture-failed", "onboarding"), ("onboarding", "capture-failed")):
        banner = NoticeBanner()
        sink = BannerSink(banner)
        built = {
            "capture-failed": error_notice("capture-failed", "截屏翻译失败"),
            "onboarding": sticky("onboarding", Severity.WARNING),
        }
        for notice_id in order:
            sink.present(built[notice_id])
        assert banner.notice.notice_id == "capture-failed", order


def test_the_dropped_message_is_not_lost_only_deferred(qt_app):
    """Dropping a copy is only safe because the centre still holds it."""
    center = NoticeCenter()
    host, banner = hosted_banner()
    banner.cleared.connect(center.replay)
    center.register_sink(BannerSink(banner))

    center.post(error_notice("capture-failed", "截屏翻译失败"))
    center.post(sticky("onboarding", Severity.WARNING))
    assert banner.notice.notice_id == "capture-failed"
    assert {item.notice_id for item in center.active()} == {"capture-failed", "onboarding"}

    # The user acts on the failure; the warning underneath surfaces on its own.
    center.revoke("capture-failed")
    assert banner.notice is not None, "the slot went empty with a message still active"
    assert banner.notice.notice_id == "onboarding"
    host.hide()


def test_saving_settings_does_not_wipe_a_standing_failure(qt_app):
    """The confirmation is worth less than the error it would have hidden.

    Both stay reachable: the error keeps the slot, and the confirmation is
    in the history either way.
    """
    center = NoticeCenter()
    host, banner = hosted_banner()
    banner.cleared.connect(center.replay)
    center.register_sink(BannerSink(banner))

    center.post(error_notice("capture-failed", "截屏翻译失败"))
    center.post(success_notice("saved", "设置已保存"))

    assert banner.notice.notice_id == "capture-failed"
    assert [item.notice_id for item in center.history()] == ["capture-failed", "saved"]
    host.hide()


def test_a_download_takes_the_slot_and_gives_it_back(qt_app):
    """The handback path that actually happens.

    Progress is the one thing allowed to cover a standing error, because
    the user just started it and it ends on its own.
    """
    center = NoticeCenter()
    host, banner = hosted_banner()
    banner.cleared.connect(center.replay)
    center.register_sink(BannerSink(banner))

    center.post(error_notice("capture-failed", "截屏翻译失败"))
    center.post(progress_notice("download", "正在下载模型", 0.25))
    assert banner.notice.notice_id == "download"

    center.revoke("download")  # the download finished

    assert banner.notice is not None, "the error did not come back"
    assert banner.notice.notice_id == "capture-failed"
    host.hide()


def test_clearing_an_empty_banner_does_not_announce_anything(qt_app):
    """Guards against clear() re-entering replay in a loop."""
    banner = NoticeBanner()
    emitted = []
    banner.cleared.connect(lambda: emitted.append(1))

    banner.clear()
    banner.clear()

    assert emitted == []


# --- and the sequence that produced the report -------------------------


def test_the_silent_autostart_sequence_end_to_end(qt_app):
    from types import SimpleNamespace
    from unittest.mock import Mock

    import screen_translator.controller as controller_module
    from screen_translator import design
    from screen_translator.config_store import ConfigStore
    from screen_translator.controller import Controller
    from screen_translator.core import Config
    from screen_translator.onboarding import StartupIntent
    from screen_translator.settings import Settings
    from screen_translator.tasks import TaskRunner

    design.apply(qt_app)
    store = ConfigStore(Config(), writer=lambda _config: None)

    class Hotkeys:
        def __init__(self, *_args, **_kwargs):
            self.current = ""

        def apply(self, sequence):
            self.current = sequence

        def close(self):
            pass

    backend = SimpleNamespace(
        kind="local",
        ocr=SimpleNamespace(mode="未加载", warmup=Mock()),
        translator=SimpleNamespace(mode="未加载"),
        ready=lambda: False,
        refresh=lambda: None,
        describe=lambda: "本地模型未下载",
        stop=lambda: None,
    )

    original = controller_module.ConfigStore
    controller_module.ConfigStore = lambda **_kwargs: store
    try:
        controller = Controller(
            qt_app,
            Settings,
            backend_factory=lambda _config: backend,
            hotkey_factory=Hotkeys,
            task_runner=TaskRunner(),
            intent=StartupIntent.AUTOSTART,
        )
    finally:
        controller_module.ConfigStore = original

    try:
        # Never opened: the only surface is the tray.
        controller.settings.hide()
        controller.on_capture_failed("处理失败（RuntimeError）")

        controller.settings.show()
        qt_app.processEvents()

        banner = controller.settings.banner
        assert banner.notice is not None
        assert banner.notice.notice_id == "capture-failed", (
            "the failure was covered by a less important message"
        )
        assert [action.action_id for action in banner.notice.actions] == ["retry-capture"]
        # The first-run warning is not lost either; it is still active and
        # takes the slot once the failure is dealt with.
        assert {item.notice_id for item in controller.notices.active()} == {
            "capture-failed",
            "onboarding",
        }
    finally:
        controller.app = SimpleNamespace(quit=lambda: None)
        controller.quit()
