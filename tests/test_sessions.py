import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from types import SimpleNamespace
from unittest.mock import Mock

from PySide6.QtGui import QImage

from screen_translator.controller import Controller


def test_stale_result_cannot_replace_new_session():
    from screen_translator.session import CaptureSession, SessionState

    session = CaptureSession(generation=4, state=SessionState.PROCESSING)
    state = SimpleNamespace(
        session=session,
        overlays=[Mock()],
        result="existing",
        refresh_language_actions=Mock(),
    )
    state._finish_stale_cancel = lambda generation: Controller._finish_stale_cancel(state, generation)
    Controller.done(state, 3, QImage(10, 10, QImage.Format.Format_RGB888))
    assert state.result == "existing"
    assert state.session.state == SessionState.PROCESSING
    state.refresh_language_actions.assert_not_called()


def test_cancelled_worker_completion_releases_busy_state():
    from screen_translator.session import CaptureSession, SessionState

    session = CaptureSession(generation=2, state=SessionState.CANCELLING)
    state = SimpleNamespace(session=session, refresh_language_actions=Mock())
    Controller._finish_stale_cancel(state, 1)
    assert session.state == SessionState.IDLE
    state.refresh_language_actions.assert_called_once()


def test_cancel_closes_all_overlays_and_invalidates_generation():
    from screen_translator.session import CaptureSession, SessionState

    overlays = [Mock(), Mock()]
    session = CaptureSession(generation=1, state=SessionState.SELECTING)
    session.token = Mock()
    inference = Mock()
    state = SimpleNamespace(
        session=session,
        overlays=overlays,
        capture=object(),
        result=object(),
        screens=[1],
        inference=inference,
        refresh_language_actions=Mock(),
    )
    Controller.cancel(state)
    assert session.token is None and session.generation == 2 and state.overlays == []
    assert session.state == SessionState.IDLE
    inference.end_capture.assert_called_once()
    for overlay in overlays:
        overlay.close.assert_called_once()


# Overlay behaviour moved to tests/test_overlay.py, which drives it through
# the view model rather than a namespace impersonating the controller.
# Language-pair and warm-up behaviour moved to tests/test_languages.py and
# tests/test_warmup_scheduling.py, which build the real services.
