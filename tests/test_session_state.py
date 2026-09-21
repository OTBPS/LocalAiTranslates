import pytest

from screen_translator.session import CaptureSession, SessionState


def test_capture_session_happy_path():
    session = CaptureSession()
    generation = session.begin()
    assert generation == 1 and session.state == SessionState.SELECTING
    session.transition(SessionState.PROCESSING)
    assert session.busy
    session.transition(SessionState.RESULT)
    session.invalidate()
    assert session.state == SessionState.IDLE


def test_capture_session_rejects_invalid_transition():
    session = CaptureSession()
    with pytest.raises(RuntimeError):
        session.transition(SessionState.RESULT)


def test_processing_cancel_waits_for_stale_worker_completion():
    session = CaptureSession()
    old_generation = session.begin()
    session.transition(SessionState.PROCESSING)
    session.invalidate()
    assert session.state == SessionState.CANCELLING
    assert session.generation == old_generation + 1
    session.finish_cancel()
    assert session.state == SessionState.IDLE and not session.busy
