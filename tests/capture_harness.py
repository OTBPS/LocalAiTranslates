"""A real `CaptureController` with fake edges.

The capture tests used to build a `SimpleNamespace` impersonating `self`
and call unbound `Controller` methods on it, which meant every one of them
silently encoded its own idea of what the controller looked like. This
builds the real object; only what is genuinely outside a capture -- the
screens, the clipboard, the thread pool, the window that picks a file
path -- is faked.
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect

from screen_translator.capture import Rect
from screen_translator.capture.session_controller import CaptureController
from screen_translator.config_store import ConfigStore
from screen_translator.core import Config
from screen_translator.graphics import ScreenShot
from screen_translator.inference import InferenceCoordinator
from screen_translator.languages import LanguageService
from screen_translator.session import SessionState

SCREEN = QRect(0, 0, 800, 600)


def inline_tasks():
    """Run background work on the calling thread, so tests stay ordered."""
    return SimpleNamespace(start=lambda target, name=None: target())


def build_capture(
    session_state: SessionState = SessionState.SELECTING,
    *,
    selection: Rect | None = None,
    outcome=None,
    config: Config | None = None,
    inference: InferenceCoordinator | None = None,
    tasks=None,
    overlays: int = 1,
    screens=None,
    pipeline=None,
    save_image=None,
) -> CaptureController:
    config = config or Config(source_language="en", target_language="zh-Hans")
    store = ConfigStore(config, writer=lambda _config: None)
    translator = SimpleNamespace(start=Mock(), stop=Mock())
    subject = CaptureController(
        app=SimpleNamespace(screens=lambda: [], clipboard=Mock()),
        config_provider=lambda: store.current,
        languages=LanguageService(store),
        inference=inference or InferenceCoordinator(lambda: translator),
        translator_provider=lambda: translator,
        tasks=tasks or inline_tasks(),
        renderer_factory=Mock(),
        ocr_provider=Mock(),
        overlay_factory=lambda *_args: Mock(),
        save_image=save_image or (lambda _image: None),
    )
    subject.store = store
    subject.overlays = [Mock() for _ in range(overlays)]
    subject.screens = screens if screens is not None else [ScreenShot(SCREEN, None, 1)]
    if pipeline is not None:
        subject.build_pipeline = lambda _generation: pipeline
    advance(subject, session_state)
    if selection is not None:
        subject.selection_model.adopt(selection)
    subject.outcome = outcome
    return subject


def advance(subject: CaptureController, session_state: SessionState) -> None:
    """Drive the session to `session_state` through legal transitions only."""
    if session_state is SessionState.IDLE:
        return
    subject.session.begin()
    if session_state is SessionState.SELECTING:
        return
    if session_state in (SessionState.RESULT, SessionState.FAILED):
        subject.session.transition(SessionState.PROCESSING)
    subject.session.transition(session_state)
