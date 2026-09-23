"""One capture, from the overlays appearing to the result being acted on.

This was the bulk of `Controller`: a session, a selection, a screenshot, a
pipeline, four signals coming back from a worker thread, and seventeen
command handlers, all sharing the same object as the tray menu, the
settings window, the shortcut and the download queue. Nothing about a
capture needs any of those, which is why the tests for it had to build a
namespace impersonating `self`.

What stays outside: deciding *whether* a capture may start (that needs the
backend and the download queue) and anything with a window in it. The
overlay is injected, and the only thing this asks a window for is a file
path to save a picture to.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from PySide6.QtCore import QObject, QRect, Signal
from PySide6.QtGui import QCursor

from ..core import Cancelled, Config
from ..graphics import ScreenShot, capture_region, to_bgr
from ..session import CaptureSession, SessionState
from .commands import CaptureCommand, allowed_commands, describe_block
from .pipeline import CapturePipeline, CaptureRequest, describe_failure
from .selection import Rect, SelectionModel, SelectionPhase
from .view import OverlayViewModel, default_hint

LOGGER = logging.getLogger(__name__)


class Events(QObject):
    """Background results coming back to the UI thread.

    Every signal carries the generation it belongs to, so a result that
    arrives after the user moved on is discarded instead of applied.
    """

    progress = Signal(int, str)
    done = Signal(int, object)
    failed = Signal(int, str)
    language_detected = Signal(int, str)


class CaptureController(QObject):
    """Owns one capture at a time, and everything drawn on top of it."""

    #: The capture moved on: anything showing its state should refresh.
    state_changed = Signal()
    #: A capture failed; the overlay keeps the framing, this reports it.
    failure_reported = Signal(str)

    def __init__(
        self,
        *,
        app,
        config_provider: Callable[[], Config],
        languages,
        inference,
        translator_provider,
        tasks,
        renderer_factory,
        ocr_provider,
        overlay_factory,
        save_image: Callable[[object], str | None] = lambda _image: None,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self.app = app
        self._config_provider = config_provider
        self.languages = languages
        self.inference = inference
        self._translator_provider = translator_provider
        self.tasks = tasks
        self._renderer_factory = renderer_factory
        self._ocr_provider = ocr_provider
        self._overlay_factory = overlay_factory
        self._save_image = save_image

        self.session = CaptureSession()
        self.events = Events()
        self.selection_model = SelectionModel()
        self.overlays: list[object] = []
        self.screens: list[ScreenShot] = []
        self.capture = None
        self.result = None
        self.outcome = None
        self.show_translation = True
        self.started_at = time.monotonic()
        self.message = ""
        self.cursor_point = QCursor.pos()

        self.events.progress.connect(self.progress)
        self.events.done.connect(self.done)
        self.events.failed.connect(self.failed)
        self.events.language_detected.connect(self.set_detected_language)

    @property
    def config(self) -> Config:
        return self._config_provider()

    @property
    def ocr(self):
        return self._ocr_provider()

    @property
    def active(self) -> bool:
        return bool(self.overlays)

    @property
    def busy(self) -> bool:
        return self.session.busy

    @property
    def generation(self) -> int:
        return self.session.generation

    @property
    def token(self):
        return self.session.token

    # -- the overlays ----------------------------------------------------

    def begin(self) -> None:
        if self.overlays or self.busy:
            return
        self.inference.begin_capture()
        generation = self.session.begin()
        self.screens = []
        for screen in self.app.screens():
            image = screen.grabWindow(0).toImage()
            image.setDevicePixelRatio(1)
            self.screens.append(
                ScreenShot(screen.geometry(), image, image.width() / screen.geometry().width())
            )
        self.selection_model = SelectionModel()
        self.cursor_point = QCursor.pos()
        self.message = ""
        self.started_at = time.monotonic()
        self.outcome = None
        self.overlays = [
            self._overlay_factory(self, screen, index)
            for index, screen in enumerate(self.screens)
        ]
        for overlay in self.overlays:
            overlay.show()
            if overlay.geometry().contains(QCursor.pos()):
                overlay.activateWindow()
                overlay.setFocus()
        self._warm_translation(generation)

    def _warm_translation(self, generation: int) -> None:
        if self.config.source_language == self.config.target_language:
            return
        token = self.token
        translator = self._translator_provider()

        def run():
            # Loading weights can outlast any reasonable slot wait, so
            # warm-up never holds the slot; it only runs while nothing else
            # owns it.
            if self.inference.owner is not None:
                return
            try:
                translator.start(token, lambda _: None)
            except Cancelled:
                pass
            except Exception as error:
                LOGGER.warning("Qwen warm-up failed: %s", type(error).__name__)

        self.tasks.start(run, name=f"qwen-warmup-{generation}")

    def repaint(self) -> None:
        for overlay in self.overlays:
            overlay.update()

    def cancel(self) -> None:
        previous_state = self.session.state
        self.inference.end_capture()
        self.session.invalidate()
        for overlay in self.overlays:
            overlay.close()
            overlay.deleteLater()
        self.overlays = []
        self.capture = self.result = self.outcome = None
        self.screens = []
        if previous_state != SessionState.PROCESSING:
            self.session.finish_cancel()
        self.state_changed.emit()

    # -- what the overlay draws ------------------------------------------

    @property
    def selection(self):
        """The selection as a ``QRect``, for the capture geometry helpers."""
        rect = self.selection_model.rect
        return None if rect is None else QRect(rect.x, rect.y, rect.width, rect.height)

    def screen_bounds(self) -> Rect:
        """The union of every captured screen, used to clamp the selection."""
        if not self.screens:
            return Rect(0, 0, 0, 0)
        left = min(item.geometry.left() for item in self.screens)
        top = min(item.geometry.top() for item in self.screens)
        right = max(item.geometry.right() for item in self.screens)
        bottom = max(item.geometry.bottom() for item in self.screens)
        return Rect(left, top, right - left, bottom - top)

    def overlay_model(self) -> OverlayViewModel:
        """Everything the overlay needs, decided here rather than read piecemeal."""
        from dataclasses import replace

        state = self.session.state
        model = OverlayViewModel(
            state=state,
            message=self.message,
            selection=self.selection_model.rect,
            handles=self.selection_model.handles()
            if state in (SessionState.SELECTING, SessionState.ADJUSTING)
            else (),
            show_translation=self.show_translation,
            result=self.result,
            result_rect=self._result_rect(),
            commands=self.commands(),
            language_pair=self.languages.describe(),
            elapsed_seconds=int(max(0.0, time.monotonic() - self.started_at)),
            capsule_screen=self._capsule_screen(),
            cursor=(self.cursor_point.x(), self.cursor_point.y()),
        )
        return replace(model, hint=default_hint(model))

    def commands(self) -> frozenset[CaptureCommand]:
        return allowed_commands(
            self.session.state, self.selection_model, has_result=self.outcome is not None
        )

    def explain(self, command: CaptureCommand) -> str:
        """Why ``command`` is unavailable, for a tooltip or the capsule."""
        return describe_block(command, self.session.state, self.selection_model)

    def _result_rect(self) -> Rect | None:
        if self.capture is None:
            return None
        rect = self.capture.logical_rect
        return Rect(rect.x(), rect.y(), rect.width(), rect.height())

    def _capsule_screen(self) -> int:
        """Show the status capsule once, on the screen holding the cursor."""
        for index, screen in enumerate(self.screens):
            if screen.geometry.contains(self.cursor_point):
                return index
        return 0

    # -- input ------------------------------------------------------------

    def handle(self, command: CaptureCommand, payload=None) -> bool:
        """Single entry point for overlay input.

        Returning False rather than doing nothing is what lets the overlay
        say why, instead of leaving a click indistinguishable from a miss.
        """
        if command not in self.commands():
            self.message = self.explain(command)
            self.repaint()
            return False
        handler = getattr(self, f"_on_{command.name.lower()}", None)
        if handler is None:
            return False
        handler(payload)
        self.repaint()
        return True

    def _on_begin_drag(self, point) -> None:
        self.selection_model.begin_drag(point)
        if self.session.state == SessionState.ADJUSTING:
            self.session.transition(SessionState.SELECTING)

    def _on_update_drag(self, point) -> None:
        self.selection_model.update_drag(point)

    def _on_end_drag(self, point) -> None:
        phase = self.selection_model.end_drag(point)
        self.selection_model.clamp(self.screen_bounds())
        if phase == SelectionPhase.ADJUSTING:
            self.session.transition(SessionState.ADJUSTING)
            if self.config.capture_confirm_on_release and self.selection_model.valid:
                self.handle(CaptureCommand.CONFIRM)

    def _on_grab_handle(self, payload) -> None:
        handle, point = payload
        self.selection_model.grab(handle, point)

    def _on_drag_handle(self, point) -> None:
        self.selection_model.drag_handle(point)
        self.selection_model.clamp(self.screen_bounds())

    def _on_release_handle(self, _payload) -> None:
        self.selection_model.release_handle()

    def _on_nudge(self, payload) -> None:
        handle, dx, dy = payload
        self.selection_model.nudge(handle, dx, dy)
        self.selection_model.clamp(self.screen_bounds())

    def _on_reselect(self, _payload) -> None:
        self.selection_model.reset()
        self.session.transition(SessionState.SELECTING)

    def _on_cancel(self, _payload) -> None:
        self.cancel()

    def _on_retry(self, _payload) -> None:
        self.selected()

    def _on_toggle_view(self, _payload) -> None:
        self.show_translation = not self.show_translation

    def _on_confirm(self, _payload) -> None:
        self.selected()

    def _on_copy_text(self, _payload) -> None:
        text = "\n\n".join(item.text for item in self.outcome.translated)
        self.app.clipboard().setText(text)
        self.message = "译文已复制"

    def _on_copy_image(self, _payload) -> None:
        self.app.clipboard().setImage(self.result)
        self.message = "译图已复制"

    def _on_save_image(self, _payload) -> None:
        path = self._save_image(self.result)
        self.message = f"已保存到 {path}" if path else ""

    def _on_retranslate(self, _payload) -> None:
        self.session.transition(SessionState.PROCESSING)
        self.outcome = self.result = None
        self.started_at = time.monotonic()
        self.message = ""
        self._start_pipeline()

    def _on_swap_languages(self, _payload) -> None:
        if not self.languages.swap():
            self.message = "自动识别需先完成一次识别，且输入输出语言不能相同"
            return
        self._on_retranslate(None)

    # -- running the pipeline ---------------------------------------------

    def selected(self) -> None:
        if not self.selection_model.valid:
            self.message = self.explain(CaptureCommand.CONFIRM)
            self.repaint()
            return
        self.capture = capture_region(self.screens, self.selection)
        self.outcome = self.result = None
        self.session.transition(SessionState.PROCESSING)
        self.started_at = time.monotonic()
        self.message = "准备识别文字…"
        self._start_pipeline()

    def _start_pipeline(self) -> None:
        """Run the pipeline over the capture already in memory.

        Retranslating reuses this rather than grabbing the screen again: the
        screenshot has not changed, and re-grabbing would pick up whatever is
        now on top of it.
        """
        for overlay in self.overlays:
            overlay.set_interaction_state("working")
        self.state_changed.emit()
        generation = self.generation
        token = self.token

        pipeline = self.build_pipeline(generation)
        request = CaptureRequest(
            self.capture.image,
            self.config.source_language,
            self.config.target_language,
        )

        def run():
            try:
                outcome = pipeline.run(
                    request,
                    token,
                    lambda text: self.events.progress.emit(generation, text),
                )
                self.events.done.emit(generation, outcome)
            except Cancelled:
                self.events.done.emit(generation, None)
            except Exception as error:
                self.events.failed.emit(generation, describe_failure(error))

        self.tasks.start(run, name=f"capture-pipeline-{generation}")

    def build_pipeline(self, generation: int) -> CapturePipeline:
        """Assemble the pipeline for one capture.

        The generation is bound here so a late language detection cannot be
        applied to a newer session.
        """
        return CapturePipeline(
            ocr_provider=self._ocr_provider,
            inference=self.inference,
            renderer_factory=self._renderer_factory,
            to_bgr=to_bgr,
            on_language_detected=lambda language: self.events.language_detected.emit(
                generation, language
            ),
        )

    # -- results coming back ----------------------------------------------

    def set_detected_language(self, generation: int, language: str) -> None:
        """Apply a detection only to the capture that produced it."""
        if self.session.is_current(generation):
            self.languages.detect(language)

    def progress(self, generation: int, text: str) -> None:
        if self.session.is_current(generation) and self.overlays:
            self.message = text
            self.repaint()

    def _finish_stale_cancel(self, generation: int) -> None:
        if (
            self.session.state == SessionState.CANCELLING
            and generation + 1 == self.session.generation
        ):
            self.session.finish_cancel()
            self.state_changed.emit()

    def done(self, generation: int, outcome) -> None:
        if not self.session.is_current(generation):
            self._finish_stale_cancel(generation)
            return
        self.inference.end_capture()
        if not self.overlays or outcome is None:
            return
        self.outcome = outcome
        self.result = outcome.rendered
        self.show_translation = True
        self.session.transition(SessionState.RESULT)
        for overlay in self.overlays:
            overlay.set_interaction_state("result")
        self.message = ""
        self.state_changed.emit()
        self.repaint()

    def failed(self, generation: int, message: str) -> None:
        if not self.session.is_current(generation):
            self._finish_stale_cancel(generation)
            return
        self.inference.end_capture()
        if self.overlays:
            # Keep the overlay and the selection on screen. Tearing them down
            # discarded the user's framing and left the error with nowhere
            # reliable to appear.
            self.session.transition(SessionState.FAILED)
            self.message = message
            for overlay in self.overlays:
                overlay.set_interaction_state("result")
            self.repaint()
        else:
            self.session.transition(SessionState.IDLE)
        self.state_changed.emit()
        self.failure_reported.emit(message)
