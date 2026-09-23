import os
from types import SimpleNamespace
from unittest.mock import Mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import pytest
from PySide6.QtCore import QRect, QTimer
from PySide6.QtGui import QImage

from screen_translator.capture import Rect, SelectionModel
from screen_translator.controller import Controller
from screen_translator.core import CancellationToken, Cancelled, Config
from screen_translator.feedback import Occupancy
from screen_translator.inference import MANUAL, InferenceBusy, InferenceCoordinator
from screen_translator.session import CaptureSession, SessionState


def test_toggle_cancels_a_running_manual_translation_before_capturing(monkeypatch):
    monkeypatch.setattr(QTimer, "singleShot", lambda _delay, _callback: None)
    token = CancellationToken()
    arbiter = InferenceCoordinator(lambda: None)
    arbiter.register_manual(token)
    state = SimpleNamespace(
        overlays=[],
        busy=False,
        occupancy=lambda: Occupancy(),
        config=Config(),
        backend=SimpleNamespace(ready=lambda: True, kind="local"),
        inference=arbiter,
        settings=Mock(),
        tray=Mock(),
        notices=Mock(),
        begin=Mock(),
    )

    Controller.toggle(state)

    assert token.event.is_set()
    state.settings.hide.assert_called_once()


def test_begin_marks_the_capture_active_so_manual_requests_are_refused():
    arbiter = InferenceCoordinator(lambda: None)
    state = SimpleNamespace(
        overlays=[],
        busy=False,
        session=CaptureSession(),
        app=SimpleNamespace(screens=lambda: []),
        config=Config(source_language="en", target_language="en"),
        inference=arbiter,
        tasks=Mock(),
    )

    Controller.begin(state)

    assert arbiter.capture_active is True
    with pytest.raises(InferenceBusy):
        with arbiter.reserve(MANUAL):
            pass


def test_translation_warmup_is_skipped_while_another_task_owns_the_slot():
    arbiter = InferenceCoordinator(lambda: None)
    translator = Mock()
    state = SimpleNamespace(
        overlays=[],
        busy=False,
        session=CaptureSession(),
        app=SimpleNamespace(screens=lambda: []),
        config=Config(source_language="en", target_language="zh-Hans"),
        inference=arbiter,
        tasks=SimpleNamespace(start=lambda target, name: target()),
        translator=translator,
        token=CancellationToken(),
    )

    with arbiter.reserve(MANUAL):
        arbiter._capture_active = False
        Controller.begin(state)

    translator.start.assert_not_called()

    Controller.begin(state)
    translator.start.assert_called_once()


def capture_state(pipeline, session=None):
    """The controller surface `selected()` touches, and nothing more.

    What the pipeline itself does is covered by test_capture_pipeline.py;
    this is about the wiring between a session and that pipeline.
    """
    session = session or CaptureSession()
    if session.state == SessionState.IDLE:
        session.begin()
    events = SimpleNamespace(
        progress=Mock(), done=Mock(), failed=Mock(), language_detected=Mock()
    )
    selection = SelectionModel()
    selection.adopt(Rect(0, 0, 40, 40))
    state = SimpleNamespace(
        selection_model=selection,
        selection=QRect(0, 0, 40, 40),
        screens=[],
        session=session,
        generation=session.generation,
        token=session.token,
        overlays=[Mock()],
        capture=SimpleNamespace(image=QImage(4, 4, QImage.Format.Format_RGB888)),
        outcome=None,
        result=None,
        started_at=0.0,
        config=Config(source_language="en", target_language="zh-Hans"),
        events=events,
        build_pipeline=lambda _generation: pipeline,
        tasks=SimpleNamespace(start=lambda target, name: target()),
        refresh_language_actions=Mock(),
        notices=Mock(),
        repaint=Mock(),
        message="",
    )
    state._start_pipeline = lambda: Controller._start_pipeline(state)
    return state


def test_a_successful_capture_reports_the_rendered_result(monkeypatch):
    monkeypatch.setattr(
        "screen_translator.controller.capture_region",
        lambda _screens, _selection: SimpleNamespace(
            image=QImage(4, 4, QImage.Format.Format_RGB888)
        ),
    )
    pipeline = SimpleNamespace(
        run=lambda request, token, progress: SimpleNamespace(rendered="image")
    )
    state = capture_state(pipeline)

    Controller.selected(state)

    state.events.done.emit.assert_called_once()
    # The whole outcome is reported, not just the picture: the result layer
    # needs the translated blocks to offer "copy translation".
    assert state.events.done.emit.call_args.args[1].rendered == "image"
    state.events.failed.emit.assert_not_called()


def test_a_cancelled_capture_reports_no_result_rather_than_a_failure(monkeypatch):
    monkeypatch.setattr(
        "screen_translator.controller.capture_region",
        lambda _screens, _selection: SimpleNamespace(
            image=QImage(4, 4, QImage.Format.Format_RGB888)
        ),
    )

    def cancelled(*_args):
        raise Cancelled()

    state = capture_state(SimpleNamespace(run=cancelled))

    Controller.selected(state)

    assert state.events.done.emit.call_args.args[1] is None
    state.events.failed.emit.assert_not_called()


def test_a_failed_capture_reports_a_message_meant_for_a_reader(monkeypatch):
    monkeypatch.setattr(
        "screen_translator.controller.capture_region",
        lambda _screens, _selection: SimpleNamespace(
            image=QImage(4, 4, QImage.Format.Format_RGB888)
        ),
    )

    def broken(*_args):
        raise KeyError("internal detail")

    state = capture_state(SimpleNamespace(run=broken))

    Controller.selected(state)

    state.events.done.emit.assert_not_called()
    message = state.events.failed.emit.call_args.args[1]
    assert "KeyError" in message
    assert "internal detail" not in message
