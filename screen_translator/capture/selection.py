"""The selection rectangle and what can be done to it.

The overlay drew four corner handles that were not draggable, and releasing
the mouse committed the selection immediately -- there was no moment in which
a selection existed and could still be corrected. Worse, a selection under
the minimum size destroyed the whole session and sent the user back to the
hotkey.

Pure values and pure arithmetic, deliberately: no Qt, so every hit test,
clamp and nudge is testable without a window. The overlay converts to and
from ``QRect`` at its own boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

MIN_SELECTION = 12
HANDLE_TOLERANCE = 10
HANDLE_SIZE = 10
NUDGE_STEP = 1
NUDGE_STEP_LARGE = 10


class SelectionPhase(StrEnum):
    EMPTY = "empty"
    DRAWING = "drawing"
    ADJUSTING = "adjusting"


class Handle(StrEnum):
    TOP_LEFT = "top-left"
    TOP = "top"
    TOP_RIGHT = "top-right"
    LEFT = "left"
    RIGHT = "right"
    BOTTOM_LEFT = "bottom-left"
    BOTTOM = "bottom"
    BOTTOM_RIGHT = "bottom-right"
    BODY = "body"


_EDGES = {
    Handle.TOP_LEFT: (True, True, False, False),
    Handle.TOP: (False, True, False, False),
    Handle.TOP_RIGHT: (False, True, True, False),
    Handle.LEFT: (True, False, False, False),
    Handle.RIGHT: (False, False, True, False),
    Handle.BOTTOM_LEFT: (True, False, False, True),
    Handle.BOTTOM: (False, False, False, True),
    Handle.BOTTOM_RIGHT: (False, False, True, True),
}


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    @property
    def valid(self) -> bool:
        return self.width >= MIN_SELECTION and self.height >= MIN_SELECTION

    def contains(self, point: tuple[int, int]) -> bool:
        x, y = point
        return self.x <= x <= self.right and self.y <= y <= self.bottom

    @staticmethod
    def spanning(first: tuple[int, int], second: tuple[int, int]) -> Rect:
        (x1, y1), (x2, y2) = first, second
        return Rect(min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1))


class SelectionModel:
    """The selection in progress, and the edits allowed on it."""

    def __init__(self) -> None:
        self._rect: Rect | None = None
        self._anchor: tuple[int, int] | None = None
        self._handle: Handle | None = None
        self._grab_origin: tuple[int, int] | None = None
        self._grab_rect: Rect | None = None
        self.phase = SelectionPhase.EMPTY

    @property
    def rect(self) -> Rect | None:
        return self._rect

    @property
    def valid(self) -> bool:
        return self._rect is not None and self._rect.valid

    @property
    def active_handle(self) -> Handle | None:
        return self._handle

    def reset(self) -> None:
        self.__init__()

    # -- drawing ---------------------------------------------------------

    def begin_drag(self, point: tuple[int, int]) -> None:
        self._anchor = point
        self._rect = Rect.spanning(point, point)
        self.phase = SelectionPhase.DRAWING

    def update_drag(self, point: tuple[int, int]) -> None:
        if self._anchor is None:
            return
        self._rect = Rect.spanning(self._anchor, point)

    def end_drag(self, point: tuple[int, int]) -> SelectionPhase:
        """Finish drawing and move to adjusting rather than committing.

        Returning to EMPTY on a stray click is what stops a mis-click from
        leaving an unusable one-pixel selection behind.
        """
        if self._anchor is None:
            return self.phase
        self._rect = Rect.spanning(self._anchor, point)
        self._anchor = None
        self.phase = (
            SelectionPhase.ADJUSTING
            if self._rect.width or self._rect.height
            else SelectionPhase.EMPTY
        )
        return self.phase

    # -- adjusting -------------------------------------------------------

    def handles(self) -> tuple[tuple[Handle, Rect], ...]:
        if self._rect is None:
            return ()
        rect = self._rect
        half = HANDLE_SIZE // 2
        centres = {
            Handle.TOP_LEFT: (rect.x, rect.y),
            Handle.TOP: (rect.x + rect.width // 2, rect.y),
            Handle.TOP_RIGHT: (rect.right, rect.y),
            Handle.LEFT: (rect.x, rect.y + rect.height // 2),
            Handle.RIGHT: (rect.right, rect.y + rect.height // 2),
            Handle.BOTTOM_LEFT: (rect.x, rect.bottom),
            Handle.BOTTOM: (rect.x + rect.width // 2, rect.bottom),
            Handle.BOTTOM_RIGHT: (rect.right, rect.bottom),
        }
        return tuple(
            (handle, Rect(x - half, y - half, HANDLE_SIZE, HANDLE_SIZE))
            for handle, (x, y) in centres.items()
        )

    def hit_test(self, point: tuple[int, int]) -> Handle | None:
        if self._rect is None:
            return None
        x, y = point
        for handle, box in self.handles():
            if (
                box.x - HANDLE_TOLERANCE <= x <= box.right + HANDLE_TOLERANCE
                and box.y - HANDLE_TOLERANCE <= y <= box.bottom + HANDLE_TOLERANCE
            ):
                return handle
        return Handle.BODY if self._rect.contains(point) else None

    def grab(self, handle: Handle, point: tuple[int, int]) -> None:
        self._handle = handle
        self._grab_origin = point
        self._grab_rect = self._rect

    def drag_handle(self, point: tuple[int, int]) -> None:
        if self._handle is None or self._grab_rect is None or self._grab_origin is None:
            return
        dx = point[0] - self._grab_origin[0]
        dy = point[1] - self._grab_origin[1]
        if self._handle is Handle.BODY:
            self._rect = Rect(
                self._grab_rect.x + dx,
                self._grab_rect.y + dy,
                self._grab_rect.width,
                self._grab_rect.height,
            )
            return
        self._rect = _resize(self._grab_rect, self._handle, dx, dy)

    def release_handle(self) -> None:
        self._handle = None
        self._grab_origin = None
        self._grab_rect = None

    def nudge(self, handle: Handle, dx: int, dy: int) -> None:
        if self._rect is None:
            return
        if handle is Handle.BODY:
            self._rect = Rect(
                self._rect.x + dx, self._rect.y + dy, self._rect.width, self._rect.height
            )
        else:
            self._rect = _resize(self._rect, handle, dx, dy)

    def clamp(self, bounds: Rect) -> None:
        """Keep the selection inside the captured area."""
        if self._rect is None:
            return
        width = min(self._rect.width, bounds.width)
        height = min(self._rect.height, bounds.height)
        x = max(bounds.x, min(self._rect.x, bounds.right - width))
        y = max(bounds.y, min(self._rect.y, bounds.bottom - height))
        self._rect = Rect(x, y, width, height)

    def adopt(self, rect: Rect) -> None:
        self._rect = rect
        self.phase = SelectionPhase.ADJUSTING


def _resize(rect: Rect, handle: Handle, dx: int, dy: int) -> Rect:
    left, top, right, bottom = _EDGES[handle]
    x1 = rect.x + (dx if left else 0)
    y1 = rect.y + (dy if top else 0)
    x2 = rect.right + (dx if right else 0)
    y2 = rect.bottom + (dy if bottom else 0)
    # Dragging an edge past its opposite flips the rectangle rather than
    # producing a negative size.
    return Rect(min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1))


def describe_size(rect: Rect | None) -> str:
    if rect is None:
        return ""
    return f"{rect.width} × {rect.height}"
