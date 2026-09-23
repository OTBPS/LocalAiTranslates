import os
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import numpy
import pytest
from PySide6.QtCore import QRect, QTimer
from PySide6.QtGui import QImage

from screen_translator.controller import Controller
from screen_translator.core import CancellationToken, Config, OcrLine, OcrResult, TranslatedBlock
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


def test_capture_pipeline_holds_the_inference_slot_for_the_whole_translation(monkeypatch):
    monkeypatch.setattr("screen_translator.controller.to_array", lambda _image: numpy.zeros((4, 4, 3), "uint8"))
    monkeypatch.setattr(
        "screen_translator.controller.capture_region",
        lambda _screens, _selection: SimpleNamespace(image=QImage(4, 4, QImage.Format.Format_RGB888)),
    )
    observed = {}

    class Engine:
        mode = "CUDA"

        def translate(self, blocks, token, progress, source, target, detected):
            observed["owner"] = arbiter.owner
            try:
                with arbiter.reserve(MANUAL):
                    observed["manual"] = "granted"
            except InferenceBusy:
                observed["manual"] = "refused"
            return [TranslatedBlock(block, "译文") for block in blocks]

    arbiter = InferenceCoordinator(Engine)
    session = CaptureSession()
    session.begin()
    session.transition(SessionState.PROCESSING)
    events = SimpleNamespace(
        progress=Mock(),
        done=Mock(),
        failed=Mock(),
        language_detected=Mock(),
    )
    state = SimpleNamespace(
        selection=QRect(0, 0, 40, 40),
        screens=[],
        session=session,
        generation=session.generation,
        token=session.token,
        overlays=[Mock()],
        capture=None,
        config=Config(source_language="en", target_language="zh-Hans"),
        inference=arbiter,
        events=events,
        ocr=SimpleNamespace(
            recognize=lambda *_args: OcrResult(
                [OcrLine([(0, 0), (80, 0), (80, 18), (0, 18)], "Hello", 0.99)], "en", "CUDA", {}
            )
        ),
        _renderer_factory=lambda: SimpleNamespace(
            render=lambda *_args, **_kwargs: QImage(4, 4, QImage.Format.Format_RGB888)
        ),
        translator=SimpleNamespace(last_metrics={}),
        tasks=SimpleNamespace(start=lambda target, name: target()),
        refresh_language_actions=Mock(),
        message="",
    )

    with patch.object(Controller, "cancel", Mock()):
        Controller.selected(state)

    assert observed == {"owner": "capture", "manual": "refused"}
    events.failed.emit.assert_not_called()
    events.done.emit.assert_called_once()
    assert arbiter.owner is None
