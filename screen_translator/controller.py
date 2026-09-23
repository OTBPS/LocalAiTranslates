"""Application orchestration for capture, OCR, translation, and UI state."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon, QWidget

from .backend import Backend, create_backend
from .config_store import ConfigStore
from .contracts import OcrPort, RendererPort, TranslationPort
from .core import (
    LANGUAGE_NAMES,
    TARGET_LANGUAGES,
    CancellationToken,
    Cancelled,
    Config,
    merge_lines,
    swap_language_pair,
)
from .graphics import OverlayRenderer, ScreenShot, capture_region, to_array
from .hotkeys import HotkeyService
from .inference import CAPTURE, InferenceCoordinator
from .logging_setup import configure_logging
from .manual_translation import ManualTranslationController
from .overlay import Overlay
from .remote.host import HostService
from .remote.service import ServiceState
from .session import CaptureSession, SessionState
from .tasks import TaskRunner
from .theme import create_app_icon

LOGGER = logging.getLogger(__name__)

# How often background readiness is re-checked.  The local backend reads the
# model registry and the remote backend pings the host; both are cheap, and
# polling is what lets a client notice that the host came back online.
READINESS_INTERVAL_MS = 15000


class Events(QObject):
    progress = Signal(int, str)
    done = Signal(int, object)
    failed = Signal(int, str)
    download = Signal(str, object, object)
    downloaded = Signal(str)
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
        self._backend_factory = backend_factory
        self._renderer_factory = renderer_factory
        self.tasks = task_runner or TaskRunner()
        self.events = Events()
        self.session = CaptureSession()
        self.detected_source_language: str | None = None
        self.backend = self._backend_factory(self.config)
        # One shared inference slot; the provider indirection keeps engine swaps visible.
        self.inference = InferenceCoordinator(lambda: self.translator)
        self.manual = ManualTranslationController(self.inference, self.tasks, self)
        self.host_service = HostService(
            ocr_provider=lambda: self.ocr,
            ready_provider=lambda: self.backend.ready(),
            model_provider=lambda: self.config.translation_model,
            inference=self.inference,
            tasks=self.tasks,
        )
        self.download_token = None
        self.ocr_warmup_token = None
        self.readiness_token = None
        self.warmup_completed = False
        self.overlays: list[Overlay] = []
        self.settings = settings_factory(self)
        self.capture = None
        self.result = None
        self.screens: list[ScreenShot] = []
        self.cursor_point = QCursor.pos()

        self.tray = QSystemTrayIcon(create_app_icon(), self)
        self.tray.setToolTip("屏译 · Ctrl+Alt+T")
        menu = self._build_tray_menu()
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: (
                self.show_settings() if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None
            )
        )
        self.tray.show()

        self.hotkey = hotkey_factory(app, self.toggle)
        try:
            self.hotkey.apply(self.config.hotkey)
        except ValueError as error:
            self.tray.showMessage("快捷键不可用", str(error))

        self.configuration.changed.connect(self.on_configuration_changed)
        self.events.progress.connect(self.progress)
        self.events.done.connect(self.done)
        self.events.failed.connect(self.failed)
        self.events.download.connect(self.download_progress)
        self.events.downloaded.connect(self.download_done)
        self.events.language_detected.connect(self.set_detected_language)
        if hasattr(self.settings, "exit_requested"):
            self.settings.exit_requested.connect(self.quit)
        self.refresh_language_actions()
        self.readiness_timer = QTimer(self)
        self.readiness_timer.setInterval(READINESS_INTERVAL_MS)
        self.readiness_timer.timeout.connect(self.on_readiness_tick)
        self.readiness_timer.start()
        self.refresh_readiness()
        self.apply_host_service()
        if show_settings_when_models_missing and not self.backend.ready():
            QTimer.singleShot(0, self.show_settings)
        elif self.backend.ready():
            QTimer.singleShot(1000, self.schedule_ocr_warmup)

    @property
    def config(self) -> Config:
        return self.configuration.current

    # The engines are reached through the backend so that swapping local for
    # remote is one assignment; everything that used to read ``self.ocr``
    # keeps working unchanged.
    @property
    def ocr(self) -> OcrPort:
        return self.backend.ocr

    @property
    def translator(self) -> TranslationPort:
        return self.backend.translator

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
        if self.ocr_warmup_token:
            self.ocr_warmup_token.cancel()
            self.ocr_warmup_token = None
        self.warmup_completed = False
        self.manual.cancel()
        try:
            replacement = self._backend_factory(self.config)
        except Exception as error:
            # Keep the working backend rather than tearing it down for one
            # that could not be built; a remote backend in particular cannot
            # be reused once its session is closed.
            LOGGER.warning("Backend selection failed: %s", type(error).__name__)
            self.tray.showMessage("后端不可用", str(error))
            return
        previous, self.backend = self.backend, replacement
        previous.stop()
        self.apply_host_service()
        self.schedule_ocr_warmup()

    def apply_host_service(self) -> None:
        """Reconcile the listener with the current configuration."""
        status = self.host_service.apply(self.config)
        if status.state == ServiceState.FAILED:
            self.tray.showMessage("远程服务未启动", status.detail)
        self.settings.refresh()

    def on_readiness_tick(self) -> None:
        """Periodic UI-thread check.

        Both steps are idempotent and read only cached state, so this also
        covers the case that matters for remote mode: a host that was offline
        at start-up becomes usable without the user restarting anything.
        """
        self.refresh_readiness()
        self.schedule_ocr_warmup()

    def refresh_readiness(self) -> None:
        """Re-check backend readiness off the UI thread."""
        if self.readiness_token:
            return
        token = CancellationToken()
        self.readiness_token = token

        def run():
            try:
                self.backend.refresh()
            except Exception as error:
                LOGGER.debug("Readiness refresh failed: %s", type(error).__name__)
            finally:
                if self.readiness_token is token:
                    self.readiness_token = None

        self.tasks.start(run, name="backend-readiness")

    def schedule_ocr_warmup(self) -> None:
        # Warm up once per backend, not once per readiness tick. Locally a
        # repeat is a cheap no-op, but a remote backend turns every tick into
        # an HTTP round trip and a line in the host log. A failure leaves the
        # flag clear so the next tick retries, which is how a client recovers
        # when the host comes back.
        if self.ocr_warmup_token or self.warmup_completed or not self.backend.ready():
            return
        token = CancellationToken()
        self.ocr_warmup_token = token
        source_language = self.config.source_language

        def run():
            try:
                self.ocr.warmup(source_language, token, lambda _message: None)
                self.warmup_completed = True
            except Cancelled:
                pass
            except Exception as error:
                LOGGER.warning("OCR warm-up failed: %s", type(error).__name__)
            finally:
                if self.ocr_warmup_token is token:
                    self.ocr_warmup_token = None

        self.tasks.start(run, name="ocr-warmup")

    def _build_tray_menu(self) -> QMenu:
        menu = QMenu()
        menu.addAction("设置", self.show_settings)
        menu.addSeparator()
        self.language_action = menu.addAction("")
        self.language_action.triggered.connect(
            lambda _checked=False: self.show_settings(focus_language=True)
        )
        menu.addSeparator()
        menu.addAction("退出", self.request_quit)
        return menu

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
        source = LANGUAGE_NAMES[self.config.source_language]
        if self.config.source_language == "auto" and self.detected_source_language:
            source += f"（{LANGUAGE_NAMES[self.detected_source_language]}）"
        return f"{source} → {LANGUAGE_NAMES[self.config.target_language]}"

    def refresh_language_actions(self) -> None:
        if not hasattr(self, "language_action"):
            return
        self.language_action.setText(self.language_pair_text())
        self.tray.setToolTip(f"屏译 · {self.config.hotkey} · {self.language_pair_text()}")
        if hasattr(self, "settings"):
            self.settings.refresh()

    def swap_languages(self) -> None:
        if self.busy or self.download_token:
            return
        pair = swap_language_pair(
            self.config.source_language,
            self.config.target_language,
            self.detected_source_language,
        )
        if not pair:
            self.tray.showMessage("无法对调语言", "自动识别需先完成一次识别，且输入输出语言不能相同")
            return
        # No `settings.load_config()` here: reloading the whole form to keep
        # one pair of combo boxes in sync silently discarded every unsaved
        # edit in the window. The store announces the change instead.
        self.set_language_pair(*pair)

    def set_language_pair(self, source_language: str, target_language: str) -> bool:
        from .core import SOURCE_LANGUAGES

        if self.busy or self.download_token:
            return False
        if source_language not in SOURCE_LANGUAGES or target_language not in TARGET_LANGUAGES:
            return False
        source_changed = source_language != self.config.source_language
        if source_language == self.config.source_language and target_language == self.config.target_language:
            return True
        self.configuration.update(
            source_language=source_language,
            target_language=target_language,
        )
        if source_changed:
            self.detected_source_language = None
            warmup_token = getattr(self, "ocr_warmup_token", None)
            if warmup_token:
                warmup_token.cancel()
                self.ocr_warmup_token = None
            if hasattr(self, "schedule_ocr_warmup"):
                self.schedule_ocr_warmup()
        self.refresh_language_actions()
        return True

    def on_configuration_changed(self, config: Config) -> None:
        """Push stored values into the views without discarding unsaved edits."""
        show_languages = getattr(self.settings, "show_language_pair", None)
        if show_languages is not None:
            show_languages(config.source_language, config.target_language)

    def show_result_language_menu(self, parent, position) -> None:
        menu = QMenu(parent)
        current = menu.addAction(self.language_pair_text())
        current.setEnabled(False)
        action = menu.addAction("对调输入/输出语言（用于下次截图）")
        pair = swap_language_pair(
            self.config.source_language,
            self.config.target_language,
            self.detected_source_language,
        )
        action.setEnabled(bool(pair) and not self.busy and not self.download_token)
        action.triggered.connect(self.swap_languages)
        menu.popup(position)
        self.result_language_menu = menu

    def set_detected_language(self, generation: int, language: str) -> None:
        if not self.session.is_current(generation) or language not in TARGET_LANGUAGES:
            return
        self.detected_source_language = language
        self.refresh_language_actions()

    def toggle(self) -> None:
        if self.overlays:
            self.cancel()
            return
        if self.busy or self.download_token:
            self.tray.showMessage("正在处理", "请等待当前任务结束")
            return
        if not self.backend.ready():
            self.tray.showMessage("无法截图翻译", self.backend.describe())
            self.show_settings()
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
        self.selection = None
        self.start_point = None
        self.cursor_point = QCursor.pos()
        self.message = "拖动框选文字 · Esc 取消"
        self.overlays = [Overlay(self, screen) for screen in self.screens]
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

    def selected(self) -> None:
        if not self.selection or self.selection.width() < 12 or self.selection.height() < 12:
            self.cancel()
            self.tray.showMessage("选区太小", "请重新框选文字区域")
            return
        self.capture = capture_region(self.screens, self.selection)
        self.session.transition(SessionState.PROCESSING)
        for overlay in self.overlays:
            overlay.set_interaction_state("working")
        self.refresh_language_actions()
        self.message = "准备识别文字…"
        generation = self.generation
        token = self.token
        capture = self.capture
        source_language = self.config.source_language
        target_language = self.config.target_language

        def run():
            try:

                def progress(text):
                    self.events.progress.emit(generation, text)

                import cv2

                ocr_result = self.ocr.recognize(
                    cv2.cvtColor(to_array(capture.image), cv2.COLOR_RGB2BGR),
                    source_language,
                    token,
                    progress,
                )
                self.events.language_detected.emit(generation, ocr_result.detected_language)
                blocks = merge_lines(ocr_result.lines)
                if not blocks:
                    raise RuntimeError("没有识别到清晰的横排文字")
                translation_started = time.monotonic()
                with self.inference.reserve(CAPTURE) as engine:
                    translated = engine.translate(
                        blocks,
                        token,
                        progress,
                        source_language,
                        target_language,
                        ocr_result.detected_language,
                    )
                translation_ms = (time.monotonic() - translation_started) * 1000
                render_started = time.monotonic()
                result = self._renderer_factory().render(
                    capture.image,
                    translated,
                    token,
                    target_language,
                )
                render_ms = (time.monotonic() - render_started) * 1000
                metrics = getattr(self.translator, "last_metrics", {})
                logging.getLogger("screen_translator.performance").info(
                    "Pipeline timing ms device=%s blocks=%d batches=%d retries=%d format_repairs=%d "
                    "ocr=%.1f translation=%.1f render=%.1f",
                    ocr_result.device,
                    len(blocks),
                    metrics.get("batches", 0),
                    metrics.get("quality_retries", 0),
                    metrics.get("format_repairs", 0),
                    ocr_result.timings_ms.get("total", 0.0),
                    translation_ms,
                    render_ms,
                )
                token.check()
                self.events.done.emit(generation, result)
            except Cancelled:
                self.events.done.emit(generation, None)
            except Exception as error:
                message = (
                    str(error)
                    if isinstance(error, RuntimeError)
                    else f"处理失败（{type(error).__name__}），请检查模型或重新启动"
                )
                self.events.failed.emit(generation, message)

        self.tasks.start(run, name=f"capture-pipeline-{generation}")

    def progress(self, generation: int, text: str) -> None:
        if self.session.is_current(generation) and self.overlays:
            self.message = text
            self.repaint()

    def _finish_stale_cancel(self, generation: int) -> None:
        if self.session.state == SessionState.CANCELLING and generation + 1 == self.session.generation:
            self.session.finish_cancel()
            self.refresh_language_actions()

    def done(self, generation: int, result) -> None:
        if not self.session.is_current(generation):
            self._finish_stale_cancel(generation)
            return
        self.inference.end_capture()
        if not self.overlays or result is None:
            return
        self.result = result
        self.show_translation = True
        self.session.transition(SessionState.RESULT)
        for overlay in self.overlays:
            overlay.set_interaction_state("result")
        self.message = "左键切换原图/译文 · 右键切换语言 · Esc 或快捷键退出"
        self.refresh_language_actions()
        self.repaint()

    def failed(self, generation: int, message: str) -> None:
        if not self.session.is_current(generation):
            self._finish_stale_cancel(generation)
            return
        self.cancel()
        # The worker has already finished by the time this signal is handled.
        self.session.finish_cancel()
        self.refresh_language_actions()
        self.tray.showMessage("截屏翻译", message)

    def cancel(self) -> None:
        previous_state = self.session.state
        self.inference.end_capture()
        self.session.invalidate()
        for overlay in self.overlays:
            overlay.close()
            overlay.deleteLater()
        self.overlays = []
        self.capture = self.result = None
        self.screens = []
        if previous_state != SessionState.PROCESSING:
            self.session.finish_cancel()
        self.refresh_language_actions()

    def download_progress(self, name: str, current, total) -> None:
        self.settings.bar.show()
        self.settings.cancel_button.show()
        self.settings.set_status(f"{name} · {current / 1e9:.2f} / {total / 1e9:.2f} GB")
        self.settings.bar.setValue(int(current / total * 1000) if total else 0)

    def download_done(self, message: str) -> None:
        self.download_token = None
        self.settings.bar.hide()
        self.settings.cancel_button.hide()
        self.settings.set_status(message)
        self.refresh_language_actions()

    def quit(self) -> None:
        self.cancel()
        self.manual.cancel()
        self.readiness_timer.stop()
        for token in (self.ocr_warmup_token, self.download_token, self.readiness_token):
            if token:
                token.cancel()
        self.hotkey.close()
        # Stop accepting remote work before tearing the engines down, so an
        # in-flight request fails cleanly instead of racing the shutdown.
        self.host_service.stop()
        self.backend.stop()
        self.tasks.shutdown()
        self.tray.hide()
        self.app.quit()
