"""The capture overlay, driven by a view model and emitting commands.

Painting and input used to reach into a dozen controller attributes. These
tests speak to the overlay the way the controller now does: hand it a model,
read back the commands it produces.
"""

import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from screen_translator.capture import (
    CaptureCommand,
    Handle,
    OverlayViewModel,
    Rect,
    SelectionModel,
    allowed_commands,
    default_hint,
)
from screen_translator.graphics import ScreenShot
from screen_translator.overlay import RESULT_MENU_COMMANDS, Overlay, draw_selection_cursor
from screen_translator.session import SessionState

SIZE = QRect(0, 0, 300, 200)


@pytest.fixture(scope="module", autouse=True)
def qt_app():
    return QApplication.instance() or QApplication([])


def model_for(state, *, selection=None, has_result=False, **overrides):
    picker = SelectionModel()
    if selection is not None:
        picker.adopt(selection)
    base = OverlayViewModel(
        state=state,
        selection=picker.rect,
        handles=picker.handles(),
        commands=allowed_commands(state, picker, has_result=has_result),
        language_pair="英语 → 简体中文",
        cursor=(10, 10),
        result_rect=Rect(0, 0, 300, 200),
        **overrides,
    )
    from dataclasses import replace

    return replace(base, hint=default_hint(base))


def build(model):
    image = QImage(300, 200, QImage.Format.Format_RGB888)
    image.fill(QColor("#808080"))
    holder = SimpleNamespace(current=model)
    controller = SimpleNamespace(
        overlay_model=lambda: holder.current,
        handled=[],
        cursor_point=QPoint(0, 0),
        repaint=Mock(),
        explain=lambda command: f"当前无法{command.label}",
    )

    def handle(command, payload=None):
        controller.handled.append((command, payload))
        return command in holder.current.commands

    controller.handle = handle
    overlay = Overlay(controller, ScreenShot(SIZE, image, 1))
    return overlay, controller, holder


def commands(controller):
    return [item[0] for item in controller.handled]


def test_escape_cancels_from_every_state():
    for state in SessionState:
        overlay, controller, _holder = build(model_for(state))
        overlay.show()
        try:
            QTest.keyClick(overlay, Qt.Key.Key_Escape)
            assert CaptureCommand.CANCEL in commands(controller), state
        finally:
            overlay.close()


def test_clicking_during_processing_is_refused_rather_than_ignored():
    overlay, controller, _holder = build(model_for(SessionState.PROCESSING))
    overlay.show()
    try:
        QTest.mouseClick(overlay, Qt.MouseButton.LeftButton)

        # The command still reaches the controller, which answers "no" and
        # can say why. Previously nothing happened at all.
        assert controller.handled
        assert all(item[0] is not CaptureCommand.TOGGLE_VIEW for item in controller.handled)
    finally:
        overlay.close()


def test_a_click_in_the_result_state_toggles_the_view():
    overlay, controller, _holder = build(model_for(SessionState.RESULT, has_result=True))
    overlay.show()
    try:
        QTest.mouseClick(overlay, Qt.MouseButton.LeftButton)

        assert CaptureCommand.TOGGLE_VIEW in commands(controller)
    finally:
        overlay.close()


def test_right_click_offers_everything_that_can_be_done_with_the_result():
    overlay, controller, _holder = build(model_for(SessionState.RESULT, has_result=True))
    overlay.show()
    try:
        overlay.show_result_menu(QPoint(10, 10))

        menu = overlay.result_menu
        labels = [action.text() for action in menu.actions() if not action.isSeparator()]
        # The header names the pair; the rest are the commands. Previously
        # the only entry swapped languages for the *next* capture, so the
        # translation on screen could not be copied, saved or redone.
        assert labels[0] == "英语 → 简体中文"
        assert labels[1:] == [command.label for command in RESULT_MENU_COMMANDS]
        assert menu.actions()[0].isEnabled() is False, "the header is not a command"

        menu.actions()[2].trigger()
        assert controller.handled[-1][0] is RESULT_MENU_COMMANDS[0]
    finally:
        overlay.close()


def test_a_command_the_result_cannot_offer_is_shown_disabled_with_a_reason():
    overlay, controller, _holder = build(model_for(SessionState.RESULT, has_result=False))
    controller.explain = lambda command: f"当前无法{command.label}"
    overlay.show()
    try:
        overlay.show_result_menu(QPoint(10, 10))

        # Hiding it would look like a missing feature; disabling it without
        # a reason is the complaint this whole layer exists to fix.
        copy_text = next(
            action
            for action in overlay.result_menu.actions()
            if action.text() == CaptureCommand.COPY_TEXT.label
        )
        assert copy_text.isEnabled() is False
        assert copy_text.toolTip() == "当前无法复制译文"
    finally:
        overlay.close()


def test_the_menu_stays_shut_when_nothing_can_be_done():
    overlay, _controller, _holder = build(model_for(SessionState.SELECTING))
    overlay.show()
    try:
        overlay.show_result_menu(QPoint(10, 10))

        assert not hasattr(overlay, "result_menu")
    finally:
        overlay.close()


def test_dragging_inside_a_selection_grabs_a_handle():
    selection = Rect(50, 40, 120, 80)
    overlay, controller, _holder = build(
        model_for(SessionState.ADJUSTING, selection=selection)
    )
    overlay.show()
    try:
        # Press on the bottom-right handle.
        QTest.mousePress(overlay, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(170, 120))

        assert CaptureCommand.GRAB_HANDLE in commands(controller)
        handle, _point = controller.handled[-1][1]
        assert handle is Handle.BOTTOM_RIGHT
    finally:
        overlay.releaseMouse()
        overlay.close()


def test_arrow_keys_nudge_and_shift_nudges_further():
    overlay, controller, _holder = build(
        model_for(SessionState.ADJUSTING, selection=Rect(50, 40, 120, 80))
    )
    overlay.show()
    try:
        QTest.keyClick(overlay, Qt.Key.Key_Right)
        QTest.keyClick(overlay, Qt.Key.Key_Right, Qt.KeyboardModifier.ShiftModifier)

        steps = [item[1][1] for item in controller.handled if item[0] is CaptureCommand.NUDGE]
        assert steps == [1, 10]
    finally:
        overlay.close()


def test_return_confirms_while_adjusting_and_retries_after_a_failure():
    overlay, controller, holder = build(
        model_for(SessionState.ADJUSTING, selection=Rect(0, 0, 100, 100))
    )
    overlay.show()
    try:
        QTest.keyClick(overlay, Qt.Key.Key_Return)
        assert CaptureCommand.CONFIRM in commands(controller)

        holder.current = model_for(SessionState.FAILED, selection=Rect(0, 0, 100, 100))
        QTest.keyClick(overlay, Qt.Key.Key_Return)
        assert CaptureCommand.RETRY in commands(controller)
    finally:
        overlay.close()


def test_the_hint_is_rendered_in_every_state_including_processing():
    # The regression this exists for: the progress text used to overwrite
    # the only line, hiding "Esc 取消" exactly when the wait was longest.
    for state in (
        SessionState.SELECTING,
        SessionState.ADJUSTING,
        SessionState.PROCESSING,
        SessionState.RESULT,
        SessionState.FAILED,
    ):
        model = model_for(state, message="正在翻译 3/12")
        assert model.hint, state
        assert "Esc" in model.hint, state


def test_the_processing_hint_counts_the_seconds_spent():
    model = model_for(SessionState.PROCESSING, elapsed_seconds=37)

    # A cold start can take most of a minute; a ticking count is what
    # distinguishes working from hung.
    assert "37" in model.hint


def test_only_animated_states_run_a_repaint_timer():
    overlay, _controller, holder = build(model_for(SessionState.PROCESSING))
    overlay.show()
    try:
        overlay.grab()
        assert overlay.timer.isActive() is True

        holder.current = model_for(SessionState.RESULT, has_result=True)
        overlay.grab()

        # Ten repaints a second of every screen, for a still image.
        assert overlay.timer.isActive() is False
    finally:
        overlay.close()


def test_the_capsule_is_drawn_on_one_screen_only():
    image = QImage(300, 200, QImage.Format.Format_RGB888)
    image.fill(QColor("#202020"))
    model = model_for(SessionState.SELECTING, capsule_screen=1)
    controller = SimpleNamespace(
        overlay_model=lambda: model,
        handle=lambda *_args, **_kwargs: True,
        cursor_point=QPoint(0, 0),
        repaint=Mock(),
        show_result_menu=Mock(),
    )
    screen = ScreenShot(SIZE, image, 1)
    first = Overlay(controller, screen, 0)
    second = Overlay(controller, screen, 1)
    try:
        without = first.grab().toImage()
        with_capsule = second.grab().toImage()

        # Paper-coloured capsule fill only appears on the chosen screen.
        assert with_capsule.pixelColor(150, 40) != without.pixelColor(150, 40)
    finally:
        first.close()
        second.close()


@pytest.mark.parametrize("top", [0, 20, 60, 100, 140, 180])
def test_the_size_badge_never_hides_under_the_capsule(top):
    overlay, _controller, _holder = build(
        model_for(SessionState.SELECTING, selection=Rect(40, top, 120, 60))
    )
    try:
        region = overlay.local(Rect(40, top, 120, 60))
        badge = overlay._badge_rect(region, 80, overlay.model())

        # The capsule is painted after the selection, so anything that
        # overlaps it is simply invisible -- which is what happened to the
        # dimensions readout for every selection near the top of a screen.
        assert not badge.intersects(overlay._capsule_rect())
        assert overlay.rect().contains(badge)
    finally:
        overlay.close()


def test_the_size_badge_sits_above_the_selection_when_there_is_room():
    overlay, _controller, _holder = build(
        model_for(SessionState.SELECTING, selection=Rect(40, 150, 120, 40))
    )
    try:
        region = overlay.local(Rect(40, 150, 120, 40))

        assert overlay._badge_rect(region, 80, overlay.model()).bottom() < region.top()
    finally:
        overlay.close()


@pytest.mark.parametrize("background", ["#FFFFFF", "#000000", "#808080"])
def test_the_cursor_is_visible_on_any_background(background):
    """It is drawn on an unknown screenshot, so it cannot assume one.

    Painted rather than left to Windows because native cross cursors
    flicker while ownership moves between full-screen overlays.
    """
    image = QImage(60, 60, QImage.Format.Format_RGB32)
    image.fill(QColor(background))
    painter = QPainter(image)
    draw_selection_cursor(painter, QPoint(30, 30))
    painter.end()

    # Both arms and the centre have to differ from the background
    # somewhere, which is what the dark stroke under the light one is
    # for: neither colour alone works over every screenshot.
    for x, y in ((30, 30), (30, 14), (14, 30), (46, 30), (30, 46)):
        patch = {
            image.pixelColor(x + dx, y + dy).name()
            for dx in (-2, 0, 2)
            for dy in (-2, 0, 2)
        }
        assert patch != {QColor(background).name()}, f"invisible at {(x, y)}"


def test_the_interaction_cursor_follows_the_stage():
    overlay, _controller, _holder = build(model_for(SessionState.SELECTING))
    try:
        assert overlay.cursor().shape() == Qt.CursorShape.BlankCursor
        overlay.set_interaction_state("working")
        assert overlay.cursor().shape() == Qt.CursorShape.WaitCursor
        overlay.set_interaction_state("result")
        assert overlay.cursor().shape() == Qt.CursorShape.ArrowCursor
    finally:
        overlay.close()


def test_moving_the_mouse_keeps_the_painted_cursor_in_step():
    overlay, controller, _holder = build(model_for(SessionState.SELECTING))
    overlay.show()
    try:
        QTest.mouseMove(overlay, QPoint(80, 70))

        assert controller.cursor_point != QPoint(0, 0)
    finally:
        overlay.close()


def test_the_status_bar_blurs_what_is_actually_behind_it():
    """The one place in the project where real glass is achievable.

    The screenshot is frozen, so the strip behind the bar can be blurred
    and composited. See ADR 0005.
    """
    image = QImage(300, 200, QImage.Format.Format_RGB888)
    for x in range(300):
        for y in range(200):
            # Sharp vertical stripes: a blur has to smear them.
            image.setPixelColor(x, y, QColor("#000000" if (x // 4) % 2 else "#FFFFFF"))
    shot = ScreenShot(SIZE, image, 1)
    overlay, _controller, _holder = build(model_for(SessionState.PROCESSING))
    overlay.screen = shot
    try:
        bar = overlay._capsule_rect()
        backdrop = shot.backdrop(bar)

        assert not backdrop.isNull()
        shades = {backdrop.pixelColor(x, 20).name() for x in range(0, backdrop.width(), 3)}
        # Neither pure black nor pure white survives a blur of stripes.
        assert shades - {"#000000", "#ffffff"}, "nothing was blurred"
    finally:
        overlay.close()


def test_the_blur_is_computed_once_rather_than_every_repaint():
    """paintEvent runs ten times a second while the model works."""
    image = QImage(300, 200, QImage.Format.Format_RGB888)
    image.fill(QColor("#4488CC"))
    shot = ScreenShot(SIZE, image, 1)
    region = QRect(10, 10, 200, 40)

    first = shot.backdrop(region)
    second = shot.backdrop(region)

    assert first is second, "a fresh blur on every paint would be unusable"
    assert len(shot.glass) == 1


def test_a_capture_with_no_image_does_not_crash_the_glass():
    shot = ScreenShot(SIZE, None, 1)

    assert shot.backdrop(QRect(0, 0, 10, 10)).isNull()
