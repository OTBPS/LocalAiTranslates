"""Selection geometry, with no window in sight."""

import pytest

from screen_translator.capture.selection import (
    MIN_SELECTION,
    Handle,
    Rect,
    SelectionModel,
    SelectionPhase,
    describe_size,
)


def drawn(x=10, y=20, width=100, height=50):
    model = SelectionModel()
    model.begin_drag((x, y))
    model.end_drag((x + width, y + height))
    return model


def test_a_drag_produces_a_rectangle_in_any_direction():
    model = SelectionModel()
    model.begin_drag((100, 100))
    model.update_drag((40, 30))

    assert model.rect == Rect(40, 30, 60, 70)


def test_releasing_moves_to_adjusting_rather_than_committing():
    model = SelectionModel()
    model.begin_drag((10, 10))

    phase = model.end_drag((110, 60))

    # The whole point: a selection now exists that can still be corrected.
    assert phase == SelectionPhase.ADJUSTING
    assert model.rect == Rect(10, 10, 100, 50)


def test_a_stray_click_leaves_nothing_behind():
    model = SelectionModel()
    model.begin_drag((10, 10))

    assert model.end_drag((10, 10)) == SelectionPhase.EMPTY


def test_a_selection_below_the_minimum_is_not_valid():
    model = drawn(width=MIN_SELECTION - 1, height=100)

    assert model.rect is not None
    assert model.valid is False


def test_every_handle_is_hittable_within_tolerance():
    model = drawn()

    found = {model.hit_test((box.x + 5, box.y + 5)) for _handle, box in model.handles()}

    assert found == set(Handle) - {Handle.BODY}


def test_the_interior_reports_the_body_handle():
    model = drawn()

    assert model.hit_test((60, 45)) == Handle.BODY


def test_a_point_outside_hits_nothing():
    model = drawn()

    assert model.hit_test((500, 500)) is None


@pytest.mark.parametrize(
    ("handle", "delta", "expected"),
    [
        (Handle.RIGHT, (10, 0), Rect(10, 20, 110, 50)),
        (Handle.LEFT, (10, 0), Rect(20, 20, 90, 50)),
        (Handle.TOP, (0, 10), Rect(10, 30, 100, 40)),
        (Handle.BOTTOM, (0, 10), Rect(10, 20, 100, 60)),
        (Handle.TOP_LEFT, (5, 5), Rect(15, 25, 95, 45)),
        (Handle.BOTTOM_RIGHT, (5, 5), Rect(10, 20, 105, 55)),
    ],
)
def test_dragging_a_handle_moves_only_its_own_edges(handle, delta, expected):
    model = drawn()
    model.grab(handle, (0, 0))

    model.drag_handle(delta)

    assert model.rect == expected


def test_dragging_the_body_moves_without_resizing():
    model = drawn()
    model.grab(Handle.BODY, (0, 0))

    model.drag_handle((25, -5))

    assert model.rect == Rect(35, 15, 100, 50)


def test_dragging_an_edge_past_its_opposite_flips_instead_of_going_negative():
    model = drawn(width=100)
    model.grab(Handle.RIGHT, (0, 0))

    model.drag_handle((-150, 0))

    assert model.rect.width == 50
    assert model.rect.x == 10 - 50


def test_the_keyboard_can_adjust_by_one_pixel_or_by_ten():
    model = drawn()

    model.nudge(Handle.RIGHT, 1, 0)
    assert model.rect.width == 101

    model.nudge(Handle.RIGHT, 10, 0)
    assert model.rect.width == 111


def test_clamping_keeps_the_selection_inside_the_captured_area():
    model = drawn(x=-40, y=-30, width=100, height=50)

    model.clamp(Rect(0, 0, 200, 200))

    assert model.rect == Rect(0, 0, 100, 50)


def test_clamping_shrinks_a_selection_larger_than_the_area():
    model = drawn(x=0, y=0, width=500, height=400)

    model.clamp(Rect(0, 0, 200, 200))

    assert model.rect == Rect(0, 0, 200, 200)


def test_releasing_a_handle_ends_the_gesture():
    model = drawn()
    model.grab(Handle.RIGHT, (0, 0))

    model.release_handle()
    model.drag_handle((100, 0))

    # A drag after release must not keep resizing.
    assert model.rect == Rect(10, 20, 100, 50)
    assert model.active_handle is None


def test_size_is_described_for_the_badge():
    assert describe_size(Rect(0, 0, 640, 480)) == "640 × 480"
    assert describe_size(None) == ""
