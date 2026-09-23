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

from PySide6.QtCore import QRect

from screen_translator.capture import CaptureCommand, Handle, Rect, SelectionModel
from screen_translator.controller import Controller
from screen_translator.core import Config, OcrLine, TextBlock, TranslatedBlock
from screen_translator.graphics import ScreenShot
from screen_translator.session import CaptureSession, SessionState


def block(text):
    return TextBlock("b1", [OcrLine([(0, 0), (9, 0), (9, 9), (0, 9)], text, 0.9)])


def state(session_state=SessionState.SELECTING, *, selection=None, outcome=None):
    session = CaptureSession()
    session.begin()
    if session_state is not SessionState.SELECTING:
        if session_state in (SessionState.RESULT, SessionState.FAILED):
            session.transition(SessionState.PROCESSING)
        session.transition(session_state)
    model = SelectionModel()
    if selection is not None:
        model.adopt(selection)
    context = SimpleNamespace(
        session=session,
        selection_model=model,
        outcome=outcome,
        result=None,
        show_translation=True,
        message="",
        started_at=0.0,
        capture=None,
        overlays=[Mock()],
        screens=[ScreenShot(QRect(0, 0, 800, 600), None, 1)],
        config=Config(source_language="en", target_language="zh-Hans"),
        repaint=Mock(),
        cancel=Mock(),
        refresh_language_actions=Mock(),
        detected_source_language="en",
        app=SimpleNamespace(clipboard=Mock()),
        settings=SimpleNamespace(save_result_image=Mock(return_value="D:/out.png")),
    )
    context.handle = lambda command, payload=None: Controller.handle(
        context, command, payload
    )
    context.screen_bounds = lambda: Controller.screen_bounds(context)
    # Bind the command handlers the real controller dispatches to, so the
    # dispatch itself is under test rather than stubbed out.
    for name in dir(Controller):
        if name.startswith("_on_"):
            setattr(context, name, _bound(Controller, name, context))
    context.selected = Mock()
    context._start_pipeline = Mock()
    context.set_language_pair = Mock()
    return context


def _bound(owner, name, context):
    method = getattr(owner, name)
    return lambda payload=None: method(context, payload)


def test_releasing_the_mouse_moves_to_adjusting_rather_than_translating():
    context = state()
    context.handle(CaptureCommand.BEGIN_DRAG, (10, 10))
    context.handle(CaptureCommand.UPDATE_DRAG, (200, 120))

    context.handle(CaptureCommand.END_DRAG, (200, 120))

    assert context.session.state == SessionState.ADJUSTING
    context.selected.assert_not_called()


def test_release_can_still_translate_immediately_when_configured():
    context = state()
    context.config = Config(
        source_language="en", target_language="zh-Hans", capture_confirm_on_release=True
    )
    context.handle(CaptureCommand.BEGIN_DRAG, (10, 10))

    context.handle(CaptureCommand.END_DRAG, (200, 120))

    # A configuration-level way back to the old gesture, so the change can
    # be undone without reverting code.
    context.selected.assert_called_once()


def test_a_selection_can_be_corrected_after_release():
    context = state(SessionState.ADJUSTING, selection=Rect(10, 10, 200, 100))

    assert context.handle(CaptureCommand.GRAB_HANDLE, (Handle.RIGHT, (210, 60)))
    assert context.handle(CaptureCommand.DRAG_HANDLE, (260, 60))
    context.handle(CaptureCommand.RELEASE_HANDLE)

    assert context.selection_model.rect.width == 250


def test_a_selection_stays_inside_the_captured_screens():
    context = state(SessionState.ADJUSTING, selection=Rect(700, 500, 200, 200))

    context.handle(CaptureCommand.NUDGE, (Handle.BODY, 500, 500))

    rect = context.selection_model.rect
    assert rect.right <= 800 and rect.bottom <= 600


def test_a_selection_below_the_minimum_does_not_destroy_the_session():
    context = state(SessionState.ADJUSTING, selection=Rect(10, 10, 4, 4))

    assert context.handle(CaptureCommand.CONFIRM) is False

    # The old behaviour cancelled everything and sent the user back to the
    # hotkey; the selection is still here and still adjustable.
    assert context.session.state == SessionState.ADJUSTING
    assert context.selection_model.rect is not None
    context.cancel.assert_not_called()
    assert "12" in context.message


def test_a_refused_command_leaves_a_visible_reason():
    context = state(SessionState.PROCESSING, selection=Rect(0, 0, 100, 100))

    assert context.handle(CaptureCommand.TOGGLE_VIEW) is False

    # Previously a click during processing did nothing at all, so a missed
    # click and an ignored one looked identical.
    assert context.message
    context.repaint.assert_called()


def test_reselecting_clears_the_selection_and_returns_to_drawing():
    context = state(SessionState.ADJUSTING, selection=Rect(10, 10, 200, 100))

    context.handle(CaptureCommand.RESELECT)

    assert context.selection_model.rect is None
    assert context.session.state == SessionState.SELECTING


def test_a_failure_keeps_the_overlay_and_the_framing():
    context = state(SessionState.PROCESSING, selection=Rect(10, 10, 200, 100))
    context.inference = SimpleNamespace(end_capture=Mock())
    context.notices = Mock()

    Controller.failed(context, context.session.generation, "处理失败")

    assert context.session.state == SessionState.FAILED
    assert context.selection_model.rect is not None, "the framing must survive"
    assert context.message == "处理失败"


def test_a_failure_can_be_retried_without_reselecting():
    context = state(SessionState.FAILED, selection=Rect(10, 10, 200, 100))

    assert context.handle(CaptureCommand.RETRY)

    context.selected.assert_called_once()


def test_the_result_can_be_copied_as_text():
    outcome = SimpleNamespace(
        translated=(TranslatedBlock(block("Hello"), "你好"), TranslatedBlock(block("World"), "世界"))
    )
    context = state(SessionState.RESULT, selection=Rect(0, 0, 100, 100), outcome=outcome)

    assert context.handle(CaptureCommand.COPY_TEXT)

    context.app.clipboard().setText.assert_called_once_with("你好\n\n世界")


def test_saving_the_result_goes_through_the_window_not_the_controller():
    outcome = SimpleNamespace(translated=())
    context = state(SessionState.RESULT, selection=Rect(0, 0, 100, 100), outcome=outcome)

    assert context.handle(CaptureCommand.SAVE_IMAGE)

    context.settings.save_result_image.assert_called_once()
    assert "D:/out.png" in context.message


def test_retranslating_reuses_the_capture_instead_of_grabbing_again():
    outcome = SimpleNamespace(translated=())
    context = state(SessionState.RESULT, selection=Rect(0, 0, 100, 100), outcome=outcome)

    assert context.handle(CaptureCommand.RETRANSLATE)

    # Grabbing the screen again would pick up whatever is now on top of it.
    context._start_pipeline.assert_called_once()
    context.selected.assert_not_called()
    assert context.session.state == SessionState.PROCESSING


def test_result_actions_are_hidden_when_there_is_nothing_to_act_on():
    context = state(SessionState.RESULT, selection=Rect(0, 0, 100, 100), outcome=None)

    assert context.handle(CaptureCommand.COPY_TEXT) is False


@pytest.mark.parametrize("session_state", list(SessionState))
def test_cancelling_is_accepted_in_every_state(session_state):
    if session_state in (SessionState.IDLE, SessionState.CANCELLING):
        pytest.skip("not reachable while an overlay is on screen")
    context = state(session_state, selection=Rect(0, 0, 100, 100))

    assert context.handle(CaptureCommand.CANCEL)

    context.cancel.assert_called_once()
