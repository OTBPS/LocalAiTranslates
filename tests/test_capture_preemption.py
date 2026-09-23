"""The capture's claim on the single inference slot, and what comes back.

A capture must be able to take the slot from a manual translation, must
hold it for the whole run, and must discard anything that arrives after
the user moved on.
"""

import os
from types import SimpleNamespace
from unittest.mock import Mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import pytest
from capture_harness import build_capture, inline_tasks
from PySide6.QtCore import QTimer
from PySide6.QtGui import QImage

from screen_translator.capture import Rect
from screen_translator.controller import Controller
from screen_translator.core import CancellationToken, Cancelled, Config
from screen_translator.feedback import Occupancy
from screen_translator.inference import MANUAL, InferenceBusy, InferenceCoordinator
from screen_translator.session import SessionState


def test_toggle_cancels_a_running_manual_translation_before_capturing(monkeypatch):
    monkeypatch.setattr(QTimer, "singleShot", lambda _delay, _callback: None)
    token = CancellationToken()
    arbiter = InferenceCoordinator(lambda: None)
    arbiter.register_manual(token)
    state = SimpleNamespace(
        captures=SimpleNamespace(active=False, begin=Mock()),
        occupancy=lambda: Occupancy(),
        config=Config(),
        backend=SimpleNamespace(ready=lambda: True, kind="local"),
        inference=arbiter,
        settings=Mock(),
        notices=Mock(),
    )

    Controller.toggle(state)

    assert token.event.is_set()
    state.settings.hide.assert_called_once()


def test_begin_marks_the_capture_active_so_manual_requests_are_refused():
    arbiter = InferenceCoordinator(lambda: None)
    subject = build_capture(SessionState.IDLE, inference=arbiter, overlays=0)

    subject.begin()

    assert arbiter.capture_active is True
    with pytest.raises(InferenceBusy):
        with arbiter.reserve(MANUAL):
            pass


def test_translation_warmup_is_skipped_while_another_task_owns_the_slot():
    arbiter = InferenceCoordinator(lambda: None)
    subject = build_capture(SessionState.IDLE, inference=arbiter, overlays=0)
    translator = subject._translator_provider()

    with arbiter.reserve(MANUAL):
        arbiter._capture_active = False
        subject.begin()

    translator.start.assert_not_called()

    subject.session.invalidate()
    subject.session.finish_cancel()
    subject.begin()

    translator.start.assert_called_once()


def capture_for_pipeline(pipeline):
    subject = build_capture(SessionState.PROCESSING, selection=Rect(0, 0, 40, 40))
    subject.capture = SimpleNamespace(image=QImage(4, 4, QImage.Format.Format_RGB888))
    subject.build_pipeline = lambda _generation: pipeline
    subject.tasks = inline_tasks()
    return subject


def test_a_successful_capture_reports_the_rendered_result(monkeypatch):
    monkeypatch.setattr(
        "screen_translator.capture.session_controller.capture_region",
        lambda _screens, _selection: SimpleNamespace(
            image=QImage(4, 4, QImage.Format.Format_RGB888),
            logical_rect=None,
        ),
    )
    outcome = SimpleNamespace(rendered="image", translated=())
    subject = capture_for_pipeline(
        SimpleNamespace(run=lambda request, token, progress: outcome)
    )

    subject._start_pipeline()

    # The whole outcome is kept, not just the picture: the result layer
    # needs the translated blocks to offer "copy translation".
    assert subject.outcome is outcome
    assert subject.result == "image"
    assert subject.session.state == SessionState.RESULT


def test_a_cancelled_capture_reports_no_result_rather_than_a_failure():
    def cancelled(*_args):
        raise Cancelled()

    subject = capture_for_pipeline(SimpleNamespace(run=cancelled))

    subject._start_pipeline()

    assert subject.outcome is None
    assert subject.session.state == SessionState.PROCESSING, "cancelling is the caller's job"


def test_a_failed_capture_reports_a_message_meant_for_a_reader():
    def broken(*_args):
        raise KeyError("internal detail")

    subject = capture_for_pipeline(SimpleNamespace(run=broken))
    reported = []
    subject.failure_reported.connect(reported.append)

    subject._start_pipeline()

    assert subject.session.state == SessionState.FAILED
    assert "KeyError" in reported[0]
    assert "internal detail" not in reported[0]
