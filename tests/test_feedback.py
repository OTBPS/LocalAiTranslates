"""Routing and lifetime rules for user-visible messages."""

import pytest

from screen_translator.feedback import (
    AlwaysDecline,
    ConfirmationRequest,
    Lifetime,
    Notice,
    NoticeAction,
    NoticeCenter,
    Occupancy,
    Severity,
    Surface,
    error_notice,
    progress_notice,
    route,
    success_notice,
    supersedes,
)
from screen_translator.navigation import Destination


class FakeSink:
    def __init__(self, surface, available=True):
        self.surface = surface
        self._available = available
        self.presented = []
        self.revoked = []

    def available(self):
        return self._available

    def present(self, notice):
        self.presented.append(notice)

    def revoke(self, notice_id):
        self.revoked.append(notice_id)


def notice(**overrides):
    fields = {
        "notice_id": "n1",
        "severity": Severity.INFO,
        "title": "标题",
    }
    fields.update(overrides)
    return Notice(**fields)


def test_a_notice_goes_to_its_preferred_surface():
    subject = notice(preferred=(Surface.OVERLAY, Surface.INLINE))

    assert route(subject, {Surface.INLINE, Surface.OVERLAY, Surface.TRAY}) == (
        Surface.OVERLAY,
        Surface.INLINE,
    )


def test_an_unavailable_preference_falls_back_to_the_tray():
    subject = notice(preferred=(Surface.OVERLAY,))

    assert route(subject, {Surface.TRAY}) == (Surface.TRAY,)


def test_nothing_is_routed_when_no_surface_exists():
    assert route(notice(), set()) == ()


def test_the_same_notice_replaces_itself_rather_than_stacking():
    assert supersedes(notice(title="b"), notice(title="a")) is True
    assert supersedes(notice(notice_id="other"), notice()) is False


def test_errors_are_sticky_because_a_missed_failure_cannot_be_acted_on():
    assert error_notice("e", "失败").lifetime == Lifetime.STICKY
    assert success_notice("s", "成功").lifetime == Lifetime.TRANSIENT


def test_progress_is_clamped_to_a_fraction():
    assert progress_notice("p", "下载中", 2.5).progress == 1.0
    assert progress_notice("p", "下载中", -1.0).progress == 0.0
    assert progress_notice("p", "下载中", None).progress is None


def test_the_tray_is_only_used_when_no_better_surface_exists():
    center = NoticeCenter()
    inline = FakeSink(Surface.INLINE)
    tray = FakeSink(Surface.TRAY)
    center.register_sink(inline)
    center.register_sink(tray)

    center.post(error_notice("boom", "失败"))

    # Windows can suppress balloons entirely, so anything that matters must
    # not depend on them when a real surface is on screen.
    assert [item.notice_id for item in inline.presented] == ["boom"]
    assert tray.presented == []


def test_the_tray_takes_over_when_no_window_is_visible():
    center = NoticeCenter()
    center.register_sink(FakeSink(Surface.INLINE, available=False))
    tray = FakeSink(Surface.TRAY)
    center.register_sink(tray)

    center.post(error_notice("boom", "失败"))

    assert [item.notice_id for item in tray.presented] == ["boom"]


def test_a_sticky_notice_stays_active_until_revoked():
    center = NoticeCenter()
    sink = FakeSink(Surface.INLINE)
    center.register_sink(sink)

    center.post(error_notice("boom", "失败"))
    assert [item.notice_id for item in center.active()] == ["boom"]

    center.revoke("boom")

    assert center.active() == ()
    assert sink.revoked == ["boom"]


def test_a_transient_notice_is_not_held_open():
    center = NoticeCenter()
    center.register_sink(FakeSink(Surface.INLINE))

    center.post(success_notice("saved", "已保存"))

    assert center.active() == ()


def test_history_survives_a_surface_that_could_not_show_the_message():
    center = NoticeCenter()  # no sinks at all

    center.post(error_notice("boom", "失败"))

    # The compensation for an unreliable tray: it can still be found later.
    assert [item.notice_id for item in center.history()] == ["boom"]


def test_progress_updates_do_not_flood_the_history():
    center = NoticeCenter()
    center.register_sink(FakeSink(Surface.INLINE))

    for step in range(20):
        center.post(progress_notice("download", "下载中", step / 20))

    assert center.history() == ()
    assert len(center.active()) == 1


def test_an_action_is_reported_with_its_notice():
    center = NoticeCenter()
    seen = []
    center.action_invoked.connect(lambda notice_id, action_id: seen.append((notice_id, action_id)))
    center.post(
        error_notice(
            "no-model",
            "模型未下载",
            actions=(NoticeAction("download", "下载模型", Destination.MODEL_DOWNLOAD),),
        )
    )

    center.invoke("no-model", "download")

    assert seen == [("no-model", "download")]


def test_active_notices_can_be_filtered_by_context():
    center = NoticeCenter()
    center.post(error_notice("a", "一", context="capture"))
    center.post(error_notice("b", "二", context="remote"))

    assert [item.notice_id for item in center.active("capture")] == ["a"]


@pytest.mark.parametrize("danger", [False, True])
def test_a_missing_user_never_counts_as_consent(danger):
    port = AlwaysDecline()

    assert port.confirm(ConfirmationRequest("退出", "确定？", danger=danger)) is False


def test_occupancy_reads_as_a_boolean_and_carries_its_reason():
    assert not Occupancy()
    busy = Occupancy(True, "正在下载模型")
    assert busy
    assert busy.reason == "正在下载模型"
