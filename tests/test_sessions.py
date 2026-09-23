import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PySide6.QtGui import QImage

from screen_translator.controller import Controller
from screen_translator.feedback import Occupancy


def test_stale_result_cannot_replace_new_session():
    from screen_translator.session import CaptureSession, SessionState

    session = CaptureSession(generation=4, state=SessionState.PROCESSING)
    state = SimpleNamespace(
        session=session,
        overlays=[Mock()],
        result="existing",
        refresh_language_actions=Mock(),
    )
    state._finish_stale_cancel = lambda generation: Controller._finish_stale_cancel(state, generation)
    Controller.done(state, 3, QImage(10, 10, QImage.Format.Format_RGB888))
    assert state.result == "existing"
    assert state.session.state == SessionState.PROCESSING
    state.refresh_language_actions.assert_not_called()


def test_cancelled_worker_completion_releases_busy_state():
    from screen_translator.session import CaptureSession, SessionState

    session = CaptureSession(generation=2, state=SessionState.CANCELLING)
    state = SimpleNamespace(session=session, refresh_language_actions=Mock())
    Controller._finish_stale_cancel(state, 1)
    assert session.state == SessionState.IDLE
    state.refresh_language_actions.assert_called_once()


def test_cancel_closes_all_overlays_and_invalidates_generation():
    from screen_translator.session import CaptureSession, SessionState

    overlays = [Mock(), Mock()]
    session = CaptureSession(generation=1, state=SessionState.SELECTING)
    session.token = Mock()
    inference = Mock()
    state = SimpleNamespace(
        session=session,
        overlays=overlays,
        capture=object(),
        result=object(),
        screens=[1],
        inference=inference,
        refresh_language_actions=Mock(),
    )
    Controller.cancel(state)
    assert session.token is None and session.generation == 2 and state.overlays == []
    assert session.state == SessionState.IDLE
    inference.end_capture.assert_called_once()
    for overlay in overlays:
        overlay.close.assert_called_once()


# Overlay behaviour moved to tests/test_overlay.py, which drives it through
# the view model rather than a namespace impersonating the controller.


def test_language_pair_is_saved_immediately_and_clears_stale_detection():
    from screen_translator.config_store import ConfigStore
    from screen_translator.core import Config

    written = []
    store = ConfigStore(
        Config(source_language="auto", target_language="zh-Hans"),
        writer=written.append,
    )

    class Stand:
        """`config` reads through the store, exactly as Controller does."""

        busy = False
        configuration = store
        detected_source_language = "ja"
        refresh_language_actions = Mock()

        def occupancy(self):
            return Occupancy()

        @property
        def config(self):
            return self.configuration.current

    state = Stand()

    assert Controller.set_language_pair(state, "zh-Hans", "en")

    assert (store.current.source_language, store.current.target_language) == ("zh-Hans", "en")
    assert state.detected_source_language is None
    assert len(written) == 1, "the pair must reach disk without a separate save step"
    state.refresh_language_actions.assert_called_once()


def test_language_pair_cannot_change_while_processing():
    from screen_translator.core import Config

    config = Config(source_language="auto", target_language="zh-Hans")
    state = SimpleNamespace(
        busy=True,
        config=config,
        occupancy=lambda: Occupancy(True, "截图翻译正在进行"),
    )
    with patch.object(Config, "save") as save:
        assert not Controller.set_language_pair(state, "zh-Hans", "en")
    assert (state.config.source_language, state.config.target_language) == ("auto", "zh-Hans")
    save.assert_not_called()


def test_controller_schedules_content_free_ocr_warmup(monkeypatch, tmp_path):
    from screen_translator.core import Config

    ocr = Mock()
    tasks = Mock()
    tasks.start.side_effect = lambda target, **_kwargs: target()
    state = SimpleNamespace(
        config=Config(model_dir=str(tmp_path), source_language="auto"),
        backend=SimpleNamespace(ready=lambda: True),
        ocr=ocr,
        tasks=tasks,
        ocr_warmup_token=None,
        warmup_completed=False,
    )

    Controller.schedule_ocr_warmup(state)

    ocr.warmup.assert_called_once()
    assert ocr.warmup.call_args.args[0] == "auto"
    assert state.ocr_warmup_token is None
