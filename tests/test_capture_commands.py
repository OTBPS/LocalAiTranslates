"""Which commands are available in each state, as a full matrix.

The overlay previously answered this with scattered state checks, and a
command that matched none of them simply did nothing -- a click during
processing was indistinguishable from a missed click.
"""

import pytest

from screen_translator.capture.commands import (
    CaptureCommand,
    allowed_commands,
    describe_block,
)
from screen_translator.capture.selection import MIN_SELECTION, SelectionModel
from screen_translator.session import SessionState


def selection(width=100, height=50):
    model = SelectionModel()
    if width and height:
        model.begin_drag((0, 0))
        model.end_drag((width, height))
    return model


def test_nothing_but_drawing_is_offered_before_a_selection_exists():
    allowed = allowed_commands(SessionState.SELECTING, selection(0, 0))

    assert CaptureCommand.BEGIN_DRAG in allowed
    assert CaptureCommand.CONFIRM not in allowed


def test_a_valid_selection_can_be_confirmed():
    allowed = allowed_commands(SessionState.ADJUSTING, selection())

    assert CaptureCommand.CONFIRM in allowed
    assert CaptureCommand.RESELECT in allowed


def test_a_selection_below_the_minimum_cannot_be_confirmed():
    allowed = allowed_commands(SessionState.ADJUSTING, selection(width=4))

    assert CaptureCommand.CONFIRM not in allowed
    # Crucially it is still adjustable, rather than the session being torn
    # down and the user sent back to the hotkey.
    assert CaptureCommand.GRAB_HANDLE in allowed
    assert CaptureCommand.NUDGE in allowed


def test_cancelling_is_possible_in_every_state():
    for state in SessionState:
        assert CaptureCommand.CANCEL in allowed_commands(state, selection())


def test_processing_offers_only_cancelling():
    allowed = allowed_commands(SessionState.PROCESSING, selection())

    assert allowed == frozenset({CaptureCommand.CANCEL})


def test_the_result_layer_can_act_on_what_it_has():
    allowed = allowed_commands(SessionState.RESULT, selection(), has_result=True)

    assert {
        CaptureCommand.TOGGLE_VIEW,
        CaptureCommand.RETRANSLATE,
        CaptureCommand.COPY_TEXT,
        CaptureCommand.COPY_IMAGE,
        CaptureCommand.SAVE_IMAGE,
        CaptureCommand.SWAP_LANGUAGES,
    } <= allowed


def test_the_result_layer_hides_actions_with_nothing_to_act_on():
    allowed = allowed_commands(SessionState.RESULT, selection(), has_result=False)

    assert CaptureCommand.COPY_TEXT not in allowed
    assert CaptureCommand.TOGGLE_VIEW in allowed


def test_a_failure_offers_retry_and_reselect():
    allowed = allowed_commands(SessionState.FAILED, selection())

    assert CaptureCommand.RETRY in allowed
    assert CaptureCommand.RESELECT in allowed


def test_a_blocked_confirm_explains_the_minimum_size():
    message = describe_block(
        CaptureCommand.CONFIRM, SessionState.ADJUSTING, selection(width=4)
    )

    assert str(MIN_SELECTION) in message


def test_a_blocked_confirm_without_a_selection_says_what_to_do():
    message = describe_block(
        CaptureCommand.CONFIRM, SessionState.SELECTING, selection(0, 0)
    )

    assert "拖动框选" in message


def test_processing_explains_that_escape_still_works():
    message = describe_block(
        CaptureCommand.TOGGLE_VIEW, SessionState.PROCESSING, selection()
    )

    # A cold start can take most of a minute; the way out must stay visible.
    assert "Esc" in message


@pytest.mark.parametrize("command", list(CaptureCommand))
def test_every_command_has_a_label_for_the_interface(command):
    assert command.label


@pytest.mark.parametrize("state", list(SessionState))
def test_no_state_leaves_a_command_silently_unexplained(state):
    model = selection()
    for command in CaptureCommand:
        if command in allowed_commands(state, model):
            continue
        assert describe_block(command, state, model)
