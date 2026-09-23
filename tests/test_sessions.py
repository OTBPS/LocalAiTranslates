"""A capture that the user has moved on from must not come back.

Every background result carries the generation it belongs to; these are
the three ways a stale one used to leak into a newer session.
"""

import os
from unittest.mock import Mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from capture_harness import build_capture

from screen_translator.session import SessionState


def test_stale_result_cannot_replace_new_session():
    subject = build_capture(SessionState.PROCESSING)
    subject.result = "existing"
    changed = Mock()
    subject.state_changed.connect(changed)

    subject.done(subject.session.generation - 1, "newer picture")

    assert subject.result == "existing"
    assert subject.session.state == SessionState.PROCESSING
    changed.assert_not_called()


def test_cancelled_worker_completion_releases_busy_state():
    subject = build_capture(SessionState.PROCESSING)
    generation = subject.session.generation
    subject.session.invalidate()
    assert subject.session.state == SessionState.CANCELLING
    changed = Mock()
    subject.state_changed.connect(changed)

    # The worker for the cancelled generation finally reports back.
    subject.done(generation, None)

    assert subject.session.state == SessionState.IDLE
    changed.assert_called_once()


def test_cancel_closes_all_overlays_and_invalidates_generation():
    subject = build_capture(SessionState.SELECTING, overlays=2)
    overlays = list(subject.overlays)
    generation = subject.session.generation

    subject.cancel()

    assert subject.session.token is None
    assert subject.session.generation == generation + 1
    assert subject.overlays == []
    assert subject.session.state == SessionState.IDLE
    assert subject.screens == []
    for overlay in overlays:
        overlay.close.assert_called_once()


# Overlay behaviour moved to tests/test_overlay.py, which drives it through
# the view model rather than a namespace impersonating the controller.
# Language-pair and warm-up behaviour moved to tests/test_languages.py and
# tests/test_warmup_scheduling.py, which build the real services.
