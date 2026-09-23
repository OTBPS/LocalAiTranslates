"""Download state, and the orchestration that replaced a nullable token."""

import pytest

from screen_translator.core import Cancelled
from screen_translator.download_session import (
    DownloadSession,
    DownloadState,
)
from screen_translator.downloads import DownloadCoordinator
from screen_translator.feedback import NoticeCenter, Severity
from screen_translator.tasks import TaskRunner


class SyncRunner:
    """Runs work inline so the sequence is deterministic."""

    def start(self, target, *, name):
        target()


def coordinator(installer=None, isolator=None):
    center = NoticeCenter()
    posted = []
    center.posted.connect(posted.append)
    subject = DownloadCoordinator(
        tasks=SyncRunner(),
        notices=center,
        installer=installer or (lambda *_args: None),
        isolator=isolator or (lambda *_args: None),
    )
    return subject, center, posted


def test_the_session_walks_the_declared_states():
    session = DownloadSession()
    assert session.state == DownloadState.IDLE

    session.begin("qwen3-8b-q5-k-m")
    assert session.state == DownloadState.PREPARING
    assert session.active

    session.observe("weights.gguf", 10, 100)
    assert session.state == DownloadState.DOWNLOADING
    assert session.fraction == pytest.approx(0.1)

    session.transition(DownloadState.VERIFYING)
    session.finish(DownloadState.COMPLETED)
    assert not session.active


def test_an_undeclared_transition_is_refused():
    session = DownloadSession()

    with pytest.raises(RuntimeError, match="无效下载状态"):
        session.transition(DownloadState.COMPLETED)


def test_progress_without_a_known_total_has_no_fraction():
    session = DownloadSession()
    session.begin("m")

    session.observe("weights.gguf", 5, 0)

    assert session.fraction is None


def test_cancelling_marks_older_results_stale():
    session = DownloadSession()
    first = session.begin("m")

    second = session.invalidate()

    assert session.state == DownloadState.CANCELLING
    assert session.is_current(second)
    assert not session.is_current(first)


def test_a_completed_download_reports_success_and_clears_progress():
    subject, center, posted = coordinator()

    assert subject.start("D:/models", "qwen3-8b-q5-k-m") is True

    assert subject.snapshot.state == DownloadState.COMPLETED
    assert subject.active is False
    # The progress notice is withdrawn rather than left sitting at 100%.
    assert center.active() == ()
    assert posted[-1].severity == Severity.SUCCESS


def test_progress_reaches_the_notice_centre_as_one_updating_entry():
    def installer(_dir, _token, progress, _model):
        progress("weights.gguf", 1, 4)
        progress("weights.gguf", 2, 4)

    subject, center, posted = coordinator(installer)
    subject.start("D:/models", "m")

    fractions = [item.progress for item in posted if item.severity == Severity.PROGRESS]
    assert fractions == [None, 0.25, 0.5]
    assert center.active() == ()


def test_a_failure_is_reported_with_a_retry():
    def installer(*_args):
        raise OSError("connection reset")

    subject, _center, posted = coordinator(installer)
    subject.start("D:/models", "m")

    assert subject.snapshot.state == DownloadState.FAILED
    failure = posted[-1]
    assert failure.severity == Severity.ERROR
    assert [action.action_id for action in failure.actions] == ["retry-download"]
    # The exception type is enough context; the raw message is not shown.
    assert "OSError" in failure.detail


def test_a_cancelled_download_is_not_reported_as_a_failure():
    def installer(*_args):
        raise Cancelled()

    subject, _center, posted = coordinator(installer)
    subject.start("D:/models", "m")

    assert subject.snapshot.state == DownloadState.IDLE
    assert not any(item.severity == Severity.ERROR for item in posted)


def test_only_one_download_runs_at_a_time():
    started = []

    def installer(_dir, _token, _progress, model):
        started.append(model)

    center = NoticeCenter()
    subject = DownloadCoordinator(
        tasks=TaskRunner(), notices=center, installer=installer, isolator=lambda *_a: None
    )
    subject._session.begin("busy")  # pretend one is in flight

    assert subject.start("D:/models", "second") is False
    assert started == []


def test_redownload_quarantines_before_fetching():
    order = []

    def isolator(_dir, model):
        order.append(f"isolate:{model}")
        return None

    def installer(_dir, _token, _progress, model):
        order.append(f"install:{model}")

    subject, _center, _posted = coordinator(installer, isolator)

    subject.redownload(
        "D:/models", "m", stop_translator=lambda: order.append("stop")
    )

    # Stopping the server first is what releases the file being replaced.
    assert order == ["stop", "isolate:m", "install:m"]


def test_the_snapshot_says_whether_cancelling_is_possible():
    subject, _center, _posted = coordinator()

    assert subject.snapshot.cancellable is False

    subject._session.begin("m")

    assert subject.snapshot.cancellable is True
