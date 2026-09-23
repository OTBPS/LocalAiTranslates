"""The screenshot capture flow.

Split out of ``controller`` so that the part which does the work -- recognise,
translate, render -- can be run and tested without a window, a session or a
Qt application.
"""

from .pipeline import (
    CaptureOutcome,
    CapturePipeline,
    CaptureRequest,
    describe_failure,
)

__all__ = [
    "CaptureOutcome",
    "CapturePipeline",
    "CaptureRequest",
    "describe_failure",
]
