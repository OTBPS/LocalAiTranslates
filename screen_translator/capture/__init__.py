"""The screenshot capture flow.

Split out of ``controller`` so that the part which does the work -- recognise,
translate, render -- can be run and tested without a window, a session or a
Qt application.
"""

from .commands import CaptureCommand, allowed_commands, describe_block
from .pipeline import (
    CaptureOutcome,
    CapturePipeline,
    CaptureRequest,
    describe_failure,
)
from .selection import Handle, Rect, SelectionModel, SelectionPhase
from .view import OverlayViewModel, default_hint, state_label

__all__ = [
    "CaptureCommand",
    "CaptureOutcome",
    "CapturePipeline",
    "CaptureRequest",
    "Handle",
    "OverlayViewModel",
    "Rect",
    "SelectionModel",
    "SelectionPhase",
    "allowed_commands",
    "default_hint",
    "describe_block",
    "describe_failure",
    "state_label",
]
