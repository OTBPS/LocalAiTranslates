"""Application orchestration for capture, OCR, translation, and UI state."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import replace

from PySide6.QtCore import QObject, QRect, QTimer, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QMenu, QWidget

from .backend import Backend, create_backend
from .backend_service import BackendService
from .capture import (
    CaptureCommand,
    CapturePipeline,
    CaptureRequest,
    OverlayViewModel,
    Rect,
    SelectionModel,
    SelectionPhase,
    allowed_commands,
    default_hint,
    describe_block,
    describe_failure,
)
from .config_store import ConfigStore
from .contracts import OcrPort, RendererPort, TranslationPort
from .core import Cancelled, Config
from .downloads import DownloadCoordinator
from .feedback import (
    Notice,
    NoticeAction,
    NoticeCenter,
    Occupancy,
    Severity,
    error_notice,
)
from .feedback.sinks import TraySink
from .graphics import OverlayRenderer, ScreenShot, capture_region, to_bgr
from .hotkeys import HotkeyService
from .inference import InferenceCoordinator
from .languages import LanguageService
from .logging_setup import configure_logging
from .manual_translation import ManualTranslationController
from .navigation import Destination
from .overlay import Overlay
from .remote.host import HostService
from .remote.service import ServiceState
from .session import CaptureSession, SessionState
from .tasks import TaskRunner
from .tray import TrayIcon

LOGGER = logging.getLogger(__name__)


class Events(QObject):
    """Background results coming back to the UI thread.

    Download signals used to live here too; they now belong to
    `DownloadCoordinator`, which owns that work end to end.
    """

    progress = Signal(int, str)
    done = Signal(int, object)
    failed = Signal(int, str)
    language_detected = Signal(int, str)


class Controller(QObject):
    def __init__(
        self,
        app: QApplication,
        settings_factory: Callable[[Controller], QWidget],
        *,
        backend_factory: Callable[[Config], Backend] = create_backend,
        renderer_factory: Callable[[], RendererPort] = OverlayRenderer,
        # Injected so start-up can be exercised without registering a real
        # system-wide shortcut, which fails when another copy holds it.
        hotkey_factory: Callable[..., HotkeyService] = HotkeyService,
        task_runner: TaskRunner | None = None,
        show_settings_when_models_missing: bool = True,
    ):
        super().__init__()
        self.app = app
        # One owner for configuration. `self.config` stays as a read-only
        # view so existing call sites keep working; writes go through the
        # store so nothing has to reload a whole form to stay in sync.
        self.configuration = ConfigStore(parent=self)
        configure_logging(self.config.log_level)
        self._renderer_factory = renderer_factory
        self.tasks = task_runner or TaskRunner()
        self.events = Events()
        self.session = CaptureSession()
        self.languages = LanguageService(self.configuration, self.occupancy, self)
        # One shared inference slot; the provider indirection keeps engine swaps visible.
        self.inference = InferenceCoordinator(lambda: self.translator)
        self.manual = ManualTranslationController(self.inference, self.tasks, self)

        self.tray = TrayIcon(parent=self)
        self.tray.settings_requested.connect(self.show_settings)
        self.tray.languages_requested.connect(
            lambda: self.show_settings(focus_language=True)
        )
        self.tray.quit_requested.connect(self.request_quit)
        self.tray.show()

        # One entry point for everything the application says. Surfaces
        # register themselves; callers describe the message, not its shape.
        # Built before anything that reports, so no start-up failure has to
        # find its own way to a surface.
        self.notices = NoticeCenter(self)
        self.notices.register_sink(TraySink(self.tray.icon))
        self.notices.action_invoked.connect(self.on_notice_action)

        self.backends = BackendService(
            factory=backend_factory,
            config_provider=lambda: self.config,
            tasks=self.tasks,
            notices=self.notices,
            stop_work=self.manual.cancel,
            parent=self,
        )
        self.backends.changed.connect(self.apply_host_service)
        self.languages.source_changed.connect(self.backends.reset_warmup)
        self.languages.source_changed.connect(self.backends.warm_up)
        self.languages.changed.connect(self.refresh_language_actions)
        self.host_service = HostService(
            ocr_provider=lambda: self.ocr,
            ready_provider=self.backends.ready,
            model_provider=lambda: self.config.translation_model,
            inference=self.inference,
            tasks=self.tasks,
        )

        self.downloads = DownloadCoordinator(
            tasks=self.tasks, notices=self.notices, parent=self
        )
        self.downloads.changed.connect(self.on_download_changed)
        self.downloads.completed.connect(self.on_download_completed)

        self.overlays: list[Overlay] = []
        self.capture = None
        self.result = None
        self.outcome = None
        self.show_translation = True
        self.selection_model = SelectionModel()
        self.started_at = time.monotonic()
        self.message = ""
        self.screens: list[ScreenShot] = []
        self.cursor_point = QCursor.pos()

        # Last, because the window reads the whole surface above while it
        # builds itself -- `occupancy()` in particular, which is how a
        # missing `downloads` turned into a crash on start-up.
        self.settings = settings_factory(self)
        register_banner = getattr(self.settings, "register_notice_sinks", None)
        if register_banner is not None:
            register_banner(self.notices)

        self.hotkey = hotkey_factory(app, self.toggle)
        try:
            self.hotkey.apply(self.config.hotkey)
        except ValueError as error:
            self.notices.post(
                error_notice(
                    "hotkey-unavailable",
                    "快捷键不可用",
                    detail=str(error),
                    context="settings",
                    actions=(
                        NoticeAction(
                            "open-hotkey",
                            "更改快捷键",
                            Destination.SYSTEM_HOTKEY,
                            primary=True,
                        ),
                    ),
                )
            )

        self.configuration.changed.connect(self.on_configuration_changed)
        self.events.progress.connect(self.progress)
        self.events.done.connect(self.done)
        self.events.failed.connect(self.failed)
        self.events.language_detected.connect(self.set_detected_language)
        if hasattr(self.settings, "exit_requested"):
            self.settings.exit_requested.connect(self.quit)
        self.refresh_language_actions()
        self.backends.start()
        self.apply_host_service()
        if show_settings_when_models_missing and not self.backend.ready():
            QTimer.singleShot(0, self.show_settings)
        elif self.backend.ready():
            QTimer.singleShot(1000, self.backends.warm_up)

    @property
    def config(self) -> Config:
        return self.configuration.current

    # The engines are reached through the backend service so that swapping
    # local for remote is one assignment; everything that used to read
    # ``self.ocr`` keeps working unchanged.
    @property
    def backend(self) -> Backend:
        return self.backends.backend

    @property
    def ocr(self) -> OcrPort:
        return self.backends.ocr

    @property
    def translator(self) -> TranslationPort:
        return self.backends.translator

    @property
    def detected_source_language(self) -> str | None:
        return self.languages.detected

    @property
    def generation(self) -> int:
        return self.session.generation

    @property
    def token(self):
        return self.session.token

    @property
    def state(self) -> str:
        return self.session.state.value

    @property
    def busy(self) -> bool:
        return self.session.busy

    def replace_engines(self) -> None:
        """Rebuild the engines from the saved configuration."""
        self.backends.replace()

    def apply_host_service(self) -> None:
        """Reconcile the listener with the current configuration."""
        status = self.host_service.apply(self.config)
        if status.state == ServiceState.FAILED:
            self.notices.post(
                error_notice(
                    "host-service-failed",
                    "远程服务未启动",
                    detail=status.detail,
                    context="remote",
                    actions=(
                        NoticeAction(
                            "open-host", "检查主机设置", Destination.HOST_SERVICE, primary=True
                        ),
                    ),
                )
            )
        else:
            self.notices.revoke("host-service-failed")
        self.settings.refresh()

    def request_quit(self) -> None:
        """Use the same confirmation path for the settings window and tray menu."""
        self.settings.confirm_exit()

    def show_settings(self, *, focus_language: bool = False) -> None:
        if not self.settings.isVisible():
            self.settings.load_config()
            self.settings.refresh()
        self.settings.showNormal()
        self.settings.raise_()
        self.settings.activateWindow()
        if focus_language and hasattr(self.settings, "focus_language_controls"):
            QTimer.singleShot(0, self.settings.focus_language_controls)

    def activate_settings(self) -> None:
        if self.overlays:
            self.cancel()
        self.show_settings()

    def language_pair_text(self) -> str:
        return self.languages.describe()

    def refresh_language_actions(self) -> None:
        """Repeat the language pair wherever it is on show."""
        self.tray.describe(self.config.hotkey, self.languages.describe())
        if hasattr(self, "settings"):
            self.settings.refresh()

    def swap_languages(self) -> None:
        if self.occupancy().busy:
            return
        if self.languages.swap():
            return
        self.notices.post(
            Notice(
                "language-swap-unavailable",
                Severity.WARNING,
                "无法对调语言",
                detail="自动识别需先完成一次识别，且输入输出语言不能相同",
                context="settings",
                actions=(
                    NoticeAction("open-languages", "选择语言", Destination.CAPTURE_LANGUAGES),
                ),
            )
        )

    def set_language_pair(self, source_language: str, target_language: str) -> bool:
        return self.languages.set_pair(source_language, target_language)

    def on_configuration_changed(self, config: Config) -> None:
        """Push stored values into the views without discarding unsaved edits."""
        show_languages = getattr(self.settings, "show_language_pair", None)
        if show_languages is not None:
            show_languages(config.source_language, config.target_language)

    def on_notice_action(self, notice_id: str, action_id: str) -> None:
        """Do what the message offered.

        An action either names a place to go or a command to run; both mean
        the user can resolve the problem from where they read about it
        instead of being told to go and look for the control.
        """
        commands = {"retry-capture": self.toggle}
        for notice in (*self.notices.active(), *self.notices.history()):
            if notice.notice_id != notice_id:
                continue
            for action in notice.actions:
                if action.action_id != action_id:
                    continue
                self.notices.revoke(notice_id)
                if action.destination is not None:
                    self.show_settings()
                    navigate = getattr(self.settings, "navigate", None)
                    if navigate is not None:
                        navigate(action.destination)
                    return
                command = commands.get(action_id)
                if command is not None:
                    command()
                return

    def occupancy(self):
        """Why interactive actions are unavailable, in words a control can show.

        One predicate for every ``setEnabled`` decision, so that disabling a
        control and explaining the reason cannot drift apart.
        """
        if self.busy:
            return Occupancy(True, "截图翻译正在进行")
        if self.downloads.active:
            return Occupancy(
                True,
                "正在下载模型",
                actions=(NoticeAction("cancel-download", "取消下载"),),
            )
        return Occupancy()

    RESULT_MENU_COMMANDS = (
        CaptureCommand.COPY_TEXT,
        CaptureCommand.COPY_IMAGE,
        CaptureCommand.SAVE_IMAGE,
        CaptureCommand.RETRANSLATE,
        CaptureCommand.SWAP_LANGUAGES,
        CaptureCommand.TOGGLE_VIEW,
    )

    def show_result_menu(self, parent, position) -> None:
        """Offer what can actually be done with the result in front of you.

        Previously the only entry swapped the language pair *for the next
        capture*, so the translation on screen could not be copied, saved or
        redone without starting over.
        """
        allowed = allowed_commands(
            self.session.state, self.selection_model, has_result=self.outcome is not None
        )
        if not allowed & set(self.RESULT_MENU_COMMANDS):
            return
        menu = QMenu(parent)
        header = menu.addAction(self.language_pair_text())
        header.setEnabled(False)
        menu.addSeparator()
        for command in self.RESULT_MENU_COMMANDS:
            action = menu.addAction(command.label)
            action.setEnabled(command in allowed)
            if command not in allowed:
                action.setToolTip(
                    describe_block(command, self.session.state, self.selection_model)
                )
            action.triggered.connect(
                lambda _checked=False, chosen=command: self.handle(chosen)
            )
        menu.popup(position)
        self.result_menu = menu

    def _on_copy_text(self, _payload) -> None:
        text = "\n\n".join(item.text for item in self.outcome.translated)
        self.app.clipboard().setText(text)
        self.message = "译文已复制"

    def _on_copy_image(self, _payload) -> None:
        self.app.clipboard().setImage(self.result)
        self.message = "译图已复制"

    def _on_save_image(self, _payload) -> None:
        save = getattr(self.settings, "save_result_image", None)
        if save is None:
            return
        path = save(self.result)
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

    def set_detected_language(self, generation: int, language: str) -> None:
        """Apply a detection only to the capture that produced it."""
        if self.session.is_current(generation):
            self.languages.detect(language)

    def toggle(self) -> None:
        if self.overlays:
            self.cancel()
            return
        occupancy = self.occupancy()
        if occupancy.busy:
            self.notices.post(
                Notice(
                    "capture-busy",
                    Severity.INFO,
                    "正在处理",
                    detail=f"{occupancy.reason}，请等待当前任务结束",
                    context="capture",
                )
            )
            return
        if not self.backend.ready():
            # Land on the control that fixes it rather than on whichever tab
            # the window happened to be showing.
            destination = (
                Destination.REMOTE_PAIRING
                if self.backend.kind == "remote"
                else Destination.MODEL_DOWNLOAD
            )
            label = "检查主机连接" if self.backend.kind == "remote" else "下载模型"
            self.notices.post(
                error_notice(
                    "backend-not-ready",
                    "无法截图翻译",
                    detail=self.backend.describe(),
                    context="capture",
                    actions=(NoticeAction("fix-backend", label, destination, primary=True),),
                )
            )
            self.show_settings()
            self.settings.navigate(destination)
            return
        self.inference.cancel_preemptable()
        self.settings.hide()
        QTimer.singleShot(120, self.begin)

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
            Overlay(self, screen, index) for index, screen in enumerate(self.screens)
        ]
        for overlay in self.overlays:
            overlay.show()
            if overlay.geometry().contains(QCursor.pos()):
                overlay.activateWindow()
                overlay.setFocus()
        if self.config.source_language != self.config.target_language:
            token = self.token

            def warm_translation():
                # Loading weights can outlast any reasonable slot wait, so warm-up
                # never holds the slot; it only runs while nothing else owns it.
                if self.inference.owner is not None:
                    return
                try:
                    self.translator.start(token, lambda _: None)
                except Cancelled:
                    pass
                except Exception as error:
                    LOGGER.warning("Qwen warm-up failed: %s", type(error).__name__)

            self.tasks.start(warm_translation, name=f"qwen-warmup-{generation}")

    def repaint(self) -> None:
        for overlay in self.overlays:
            overlay.update()

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
        state = self.session.state
        commands = allowed_commands(
            state, self.selection_model, has_result=self.outcome is not None
        )
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
            commands=commands,
            language_pair=self.language_pair_text(),
            elapsed_seconds=int(max(0.0, time.monotonic() - self.started_at)),
            capsule_screen=self._capsule_screen(),
            cursor=(self.cursor_point.x(), self.cursor_point.y()),
        )
        return replace(model, hint=default_hint(model))

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

    def handle(self, command: CaptureCommand, payload=None) -> bool:
        """Single entry point for overlay input.

        Returning False rather than doing nothing is what lets the overlay
        say why, instead of leaving a click indistinguishable from a miss.
        """
        if command not in allowed_commands(
            self.session.state, self.selection_model, has_result=self.outcome is not None
        ):
            self.message = describe_block(command, self.session.state, self.selection_model)
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

    def selected(self) -> None:
        if not self.selection_model.valid:
            self.message = describe_block(
                CaptureCommand.CONFIRM, self.session.state, self.selection_model
            )
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
        self.refresh_language_actions()
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
            ocr_provider=lambda: self.ocr,
            inference=self.inference,
            renderer_factory=self._renderer_factory,
            to_bgr=to_bgr,
            on_language_detected=lambda language: self.events.language_detected.emit(
                generation, language
            ),
        )

    def progress(self, generation: int, text: str) -> None:
        if self.session.is_current(generation) and self.overlays:
            self.message = text
            self.repaint()

    def _finish_stale_cancel(self, generation: int) -> None:
        if self.session.state == SessionState.CANCELLING and generation + 1 == self.session.generation:
            self.session.finish_cancel()
            self.refresh_language_actions()

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
        self.refresh_language_actions()
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
        self.refresh_language_actions()
        # Sticky, and offering the retry directly. A capture failure used to
        # go out as a tray balloon after the overlay and the selection had
        # already been destroyed, so a user whose notification settings
        # suppress balloons lost both the result and any trace of the error.
        self.notices.post(
            error_notice(
                "capture-failed",
                "截屏翻译失败",
                detail=message,
                context="capture",
                actions=(NoticeAction("retry-capture", "重新截图", primary=True),),
            )
        )

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
        self.refresh_language_actions()

    def on_download_changed(self, snapshot) -> None:
        show_download = getattr(self.settings, "show_download", None)
        if show_download is not None:
            show_download(snapshot)
        self.refresh_language_actions()

    def on_download_completed(self, succeeded: bool) -> None:
        if succeeded:
            # New weights on disk change what the backend can do.
            self.backends.poll()

    def quit(self) -> None:
        self.cancel()
        self.manual.cancel()
        self.backends.suspend()
        self.downloads.shutdown()
        self.hotkey.close()
        # Stop accepting remote work before tearing the engines down, so an
        # in-flight request fails cleanly instead of racing the shutdown.
        self.host_service.stop()
        self.backends.stop()
        self.tasks.shutdown()
        self.tray.hide()
        self.app.quit()
