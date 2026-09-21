"""Application orchestration for capture, OCR, translation, and UI state."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import replace

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon, QWidget

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
from .inference import CAPTURE, InferenceCoordinator
from .logging_setup import configure_logging
from .manual_translation import ManualTranslationController
from .models import models_ready
from .native import Hotkey
from .ocr_engine import OcrEngine
from .overlay import Overlay
from .session import CaptureSession, SessionState
from .tasks import TaskRunner
from .theme import create_app_icon
from .translation_engine import TranslationEngine

LOGGER = logging.getLogger(__name__)


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
        ocr_factory: Callable[[str, bool], OcrPort] = OcrEngine,
        translator_factory: Callable[[str, bool, str], TranslationPort] = TranslationEngine,
        renderer_factory: Callable[[], RendererPort] = OverlayRenderer,
        task_runner: TaskRunner | None = None,
        show_settings_when_models_missing: bool = True,
    ):
        super().__init__()
        self.app = app
        self.config = Config.load()
        configure_logging(self.config.log_level)
        self._ocr_factory = ocr_factory
        self._translator_factory = translator_factory
        self._renderer_factory = renderer_factory
        self.tasks = task_runner or TaskRunner()
        self.events = Events()
        self.session = CaptureSession()
        self.detected_source_language: str | None = None
        self.ocr = self._ocr_factory(self.config.model_dir, self.config.allow_cpu)
        self.translator = self._translator_factory(
            self.config.model_dir, self.config.allow_cpu, self.config.translation_model
        )
        # One shared inference slot; the provider indirection keeps engine swaps visible.
        self.inference = InferenceCoordinator(lambda: self.translator)
        self.manual = ManualTranslationController(self.inference, self.tasks, self)
        self.download_token = None
        self.ocr_warmup_token = None
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

        self.hotkey = Hotkey(self.toggle)
        app.installNativeEventFilter(self.hotkey)
        try:
            self.hotkey.register(self.config.hotkey)
        except ValueError as error:
            self.tray.showMessage("快捷键不可用", str(error))

        self.events.progress.connect(self.progress)
        self.events.done.connect(self.done)
        self.events.failed.connect(self.failed)
        self.events.download.connect(self.download_progress)
        self.events.downloaded.connect(self.download_done)
        self.events.language_detected.connect(self.set_detected_language)
        if hasattr(self.settings, "exit_requested"):
            self.settings.exit_requested.connect(self.quit)
        self.refresh_language_actions()
        if show_settings_when_models_missing and not models_ready(
            self.config.model_dir, self.config.translation_model
        ):
            QTimer.singleShot(0, self.show_settings)
        elif models_ready(self.config.model_dir, self.config.translation_model):
            QTimer.singleShot(1000, self.schedule_ocr_warmup)

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
        self.manual.cancel()
        self.translator.stop()
        self.ocr = self._ocr_factory(self.config.model_dir, self.config.allow_cpu)
        self.translator = self._translator_factory(
            self.config.model_dir, self.config.allow_cpu, self.config.translation_model
        )
        self.schedule_ocr_warmup()

    def schedule_ocr_warmup(self) -> None:
        if self.ocr_warmup_token or not models_ready(
            self.config.model_dir, self.config.translation_model
        ):
            return
        token = CancellationToken()
        self.ocr_warmup_token = token
        source_language = self.config.source_language

        def run():
            try:
                self.ocr.warmup(source_language, token, lambda _message: None)
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
        self.set_language_pair(*pair)
        self.settings.load_config()

    def set_language_pair(self, source_language: str, target_language: str) -> bool:
        from .core import SOURCE_LANGUAGES

        if self.busy or self.download_token:
            return False
        if source_language not in SOURCE_LANGUAGES or target_language not in TARGET_LANGUAGES:
            return False
        source_changed = source_language != self.config.source_language
        if source_language == self.config.source_language and target_language == self.config.target_language:
            return True
        self.config = replace(
            self.config,
            source_language=source_language,
            target_language=target_language,
        )
        self.config.save()
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
        if not models_ready(self.config.model_dir, self.config.translation_model):
            self.show_settings()
            return
        self.inference.cancel_manual()
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
        if self.ocr_warmup_token:
            self.ocr_warmup_token.cancel()
        if self.download_token:
            self.download_token.cancel()
        self.hotkey.close()
        self.translator.stop()
        self.tasks.shutdown()
        self.tray.hide()
        self.app.quit()
