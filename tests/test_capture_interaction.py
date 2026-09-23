"""Capture interaction at the controller level.

Covers the behaviours the overlay changes were for: a selection that can be
corrected, a minimum size that does not destroy the session, a failure that
keeps the framing, and a result you can act on.
"""

import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from capture_harness import build_capture

from screen_translator.capture import CaptureCommand, Handle, Rect
from screen_translator.core import Config, OcrLine, TextBlock, TranslatedBlock
from screen_translator.session import SessionState


def block(text):
    return TextBlock("b1", [OcrLine([(0, 0), (9, 0), (9, 9), (0, 9)], text, 0.9)])


def test_releasing_the_mouse_moves_to_adjusting_rather_than_translating():
    subject = build_capture()
    subject.selected = Mock()

    subject.handle(CaptureCommand.BEGIN_DRAG, (10, 10))
    subject.handle(CaptureCommand.UPDATE_DRAG, (200, 120))
    subject.handle(CaptureCommand.END_DRAG, (200, 120))

    assert subject.session.state == SessionState.ADJUSTING
    subject.selected.assert_not_called()


def test_release_can_still_translate_immediately_when_configured():
    subject = build_capture(
        config=Config(
            source_language="en", target_language="zh-Hans", capture_confirm_on_release=True
        )
    )
    subject.selected = Mock()
    subject.handle(CaptureCommand.BEGIN_DRAG, (10, 10))

    subject.handle(CaptureCommand.END_DRAG, (200, 120))

    # A configuration-level way back to the old gesture, so the change can
    # be undone without reverting code.
    subject.selected.assert_called_once()


def test_a_selection_can_be_corrected_after_release():
    subject = build_capture(SessionState.ADJUSTING, selection=Rect(10, 10, 200, 100))

    assert subject.handle(CaptureCommand.GRAB_HANDLE, (Handle.RIGHT, (210, 60)))
    assert subject.handle(CaptureCommand.DRAG_HANDLE, (260, 60))
    subject.handle(CaptureCommand.RELEASE_HANDLE)

    assert subject.selection_model.rect.width == 250


def test_a_selection_stays_inside_the_captured_screens():
    subject = build_capture(SessionState.ADJUSTING, selection=Rect(700, 500, 200, 200))

    subject.handle(CaptureCommand.NUDGE, (Handle.BODY, 500, 500))

    rect = subject.selection_model.rect
    assert rect.right <= 800 and rect.bottom <= 600


def test_a_selection_below_the_minimum_does_not_destroy_the_session():
    subject = build_capture(SessionState.ADJUSTING, selection=Rect(10, 10, 4, 4))
    subject.cancel = Mock()

    assert subject.handle(CaptureCommand.CONFIRM) is False

    # The old behaviour cancelled everything and sent the user back to the
    # hotkey; the selection is still here and still adjustable.
    assert subject.session.state == SessionState.ADJUSTING
    assert subject.selection_model.rect is not None
    subject.cancel.assert_not_called()
    assert "12" in subject.message


def test_a_refused_command_leaves_a_visible_reason():
    subject = build_capture(SessionState.PROCESSING, selection=Rect(0, 0, 100, 100))

    assert subject.handle(CaptureCommand.TOGGLE_VIEW) is False

    # Previously a click during processing did nothing at all, so a missed
    # click and an ignored one looked identical.
    assert subject.message
    subject.overlays[0].update.assert_called()


def test_reselecting_clears_the_selection_and_returns_to_drawing():
    subject = build_capture(SessionState.ADJUSTING, selection=Rect(10, 10, 200, 100))

    subject.handle(CaptureCommand.RESELECT)

    assert subject.selection_model.rect is None
    assert subject.session.state == SessionState.SELECTING


def test_a_failure_keeps_the_overlay_and_the_framing():
    subject = build_capture(SessionState.PROCESSING, selection=Rect(10, 10, 200, 100))
    reported = []
    subject.failure_reported.connect(reported.append)

    subject.failed(subject.session.generation, "处理失败")

    assert subject.session.state == SessionState.FAILED
    assert subject.selection_model.rect is not None, "the framing must survive"
    assert subject.message == "处理失败"
    assert reported == ["处理失败"]


def test_a_failure_can_be_retried_without_reselecting():
    subject = build_capture(SessionState.FAILED, selection=Rect(10, 10, 200, 100))
    subject.selected = Mock()

    assert subject.handle(CaptureCommand.RETRY)

    subject.selected.assert_called_once()


def test_the_result_can_be_copied_as_text():
    outcome = SimpleNamespace(
        translated=(TranslatedBlock(block("Hello"), "你好"), TranslatedBlock(block("World"), "世界"))
    )
    subject = build_capture(
        SessionState.RESULT, selection=Rect(0, 0, 100, 100), outcome=outcome
    )

    assert subject.handle(CaptureCommand.COPY_TEXT)

    subject.app.clipboard().setText.assert_called_once_with("你好\n\n世界")


def test_saving_the_result_goes_through_the_window_not_the_controller():
    save = Mock(return_value="D:/out.png")
    subject = build_capture(
        SessionState.RESULT,
        selection=Rect(0, 0, 100, 100),
        outcome=SimpleNamespace(translated=()),
        save_image=save,
    )

    assert subject.handle(CaptureCommand.SAVE_IMAGE)

    save.assert_called_once()
    assert "D:/out.png" in subject.message


def test_retranslating_reuses_the_capture_instead_of_grabbing_again():
    subject = build_capture(
        SessionState.RESULT,
        selection=Rect(0, 0, 100, 100),
        outcome=SimpleNamespace(translated=()),
    )
    subject._start_pipeline = Mock()
    subject.selected = Mock()

    assert subject.handle(CaptureCommand.RETRANSLATE)

    # Grabbing the screen again would pick up whatever is now on top of it.
    subject._start_pipeline.assert_called_once()
    subject.selected.assert_not_called()
    assert subject.session.state == SessionState.PROCESSING


def test_result_actions_are_hidden_when_there_is_nothing_to_act_on():
    subject = build_capture(SessionState.RESULT, selection=Rect(0, 0, 100, 100))

    assert subject.handle(CaptureCommand.COPY_TEXT) is False


@pytest.mark.parametrize("session_state", list(SessionState))
def test_cancelling_is_accepted_in_every_state(session_state):
    if session_state in (SessionState.IDLE, SessionState.CANCELLING):
        pytest.skip("not reachable while an overlay is on screen")
    subject = build_capture(session_state, selection=Rect(0, 0, 100, 100))
    overlay = subject.overlays[0]

    assert subject.handle(CaptureCommand.CANCEL)

    assert subject.overlays == []
    overlay.close.assert_called_once()
