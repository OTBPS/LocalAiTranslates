"""What the application is made of, and the three things it can be asked to do.

Capture, downloads, the engines, the language pair, the tray and the
notice layer each own themselves; this builds them, connects them, and
answers `toggle` / `activate_settings` / `quit`. It reads as a wiring
diagram on purpose -- the point of the decomposition is that the
interesting rules are somewhere you can test them without a window.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication, QWidget

from .backend import Backend, create_backend
from .backend_service import BackendService
from .capabilities import local_runtime_available
from .capture.session_controller import CaptureController
from .config_store import ConfigStore
from .contracts import OcrPort, RendererPort, TranslationPort
from .core import Config
from .downloads import DownloadCoordinator
from .feedback import (
    Lifetime,
    Notice,
    NoticeAction,
    NoticeCenter,
    Occupancy,
    Severity,
    error_notice,
    success_notice,
)
from .feedback.sinks import TraySink
from .graphics import OverlayRenderer
from .hotkeys import HotkeyService
from .inference import InferenceCoordinator
from .languages import LanguageService
from .logging_setup import configure_logging
from .manual_translation import ManualTranslationController
from .navigation import Destination
from .onboarding import OnboardingPlan, StartupIntent, evaluate
from .overlay import Overlay
from .remote.host import HostService
from .remote.pairing import remember
from .remote.service import ServiceState
from .tasks import TaskRunner
from .tray import TrayIcon

LOGGER = logging.getLogger(__name__)


class Controller(QObject):
    #: A device completed pairing. Carried across the thread boundary from
    #: the HTTP worker that served the claim.
    device_paired = Signal(object, str)

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
        # Why the process started, which decides whether a first-run
        # problem is allowed to open a window. Guessing it from "are the
        # models ready" opened one at every login on an unset-up machine.
        intent: StartupIntent = StartupIntent.LAUNCH,
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
        # A host that came back, or weights that finished downloading, has
        # to retract the sticky first-run message by itself. Never opens a
        # window: the user is in the middle of something else.
        self.backends.ready_changed.connect(
            lambda _ready: self.review_onboarding(may_open=False)
        )
        self.languages.source_changed.connect(self.backends.reset_warmup)
        self.languages.source_changed.connect(self.backends.warm_up)
        self.languages.changed.connect(self.refresh_language_actions)
        self.host_service = HostService(
            ocr_provider=lambda: self.ocr,
            ready_provider=self.backends.ready,
            model_provider=lambda: self.config.translation_model,
            inference=self.inference,
            tasks=self.tasks,
            # Emitted rather than called: the claim is handled on an HTTP
            # worker thread, and configuration is written on the UI one.
            on_paired=lambda grant, peer: self.device_paired.emit(grant, peer),
        )
        self.device_paired.connect(self.on_device_paired)

        self.downloads = DownloadCoordinator(
            tasks=self.tasks, notices=self.notices, parent=self
        )
        self.downloads.changed.connect(self.on_download_changed)
        self.downloads.completed.connect(self.on_download_completed)

        self.captures = CaptureController(
            app=app,
            config_provider=lambda: self.config,
            languages=self.languages,
            inference=self.inference,
            translator_provider=lambda: self.translator,
            tasks=self.tasks,
            renderer_factory=renderer_factory,
            ocr_provider=lambda: self.ocr,
            overlay_factory=Overlay,
            save_image=lambda image: self.settings.save_result_image(image),
            parent=self,
        )
        self.captures.state_changed.connect(self.refresh_language_actions)
        self.captures.failure_reported.connect(self.on_capture_failed)

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
        if hasattr(self.settings, "exit_requested"):
            self.settings.exit_requested.connect(self.quit)
        self.refresh_language_actions()
        self.backends.start()
        self.apply_host_service()
        QTimer.singleShot(0, lambda: self.review_onboarding(intent))
        if self.backend.ready():
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
    def state(self) -> str:
        return self.captures.session.state.value

    @property
    def busy(self) -> bool:
        return self.captures.busy

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
        if self.captures.active:
            self.captures.cancel()
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

    def toggle(self) -> None:
        if self.captures.active:
            self.captures.cancel()
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
        # Long enough for the window to actually leave the screen before it
        # is frozen into the screenshot.
        QTimer.singleShot(120, self.captures.begin)

    def review_onboarding(
        self, intent: StartupIntent = StartupIntent.LAUNCH, *, may_open: bool = True
    ) -> OnboardingPlan:
        """Say what is still missing, and offer the control that fixes it.

        The old version was a tray balloon plus a window opened on
        whichever tab it happened to be showing -- and the balloon is the
        one surface Windows is free to suppress.
        """
        plan = evaluate(
            self.config,
            backend_ready=self.backend.ready(),
            local_runtime=local_runtime_available(),
            intent=intent,
        )
        if not plan.blocking:
            self.notices.revoke("onboarding")
            if not self.config.onboarding_completed:
                self.configuration.update(onboarding_completed=True)
            return plan
        self.notices.post(
            Notice(
                "onboarding",
                Severity.WARNING,
                plan.title,
                detail=plan.detail,
                context="settings",
                lifetime=Lifetime.STICKY,
                actions=(
                    NoticeAction(
                        "fix-onboarding",
                        plan.action_label,
                        plan.destination,
                        primary=True,
                    ),
                ),
            )
        )
        if may_open and plan.open_settings:
            self.show_settings()
            self.settings.navigate(plan.destination)
        return plan

    def on_device_paired(self, grant, peer: str) -> None:
        """Remember a device that just paired, and say so.

        Runs on the UI thread; the listener hands the grant over through a
        signal because it serves the claim on an HTTP worker.
        """
        self.configuration.update(
            paired_devices=remember(self.config.paired_devices, grant, peer)
        )
        self.apply_host_service()
        self.notices.post(
            success_notice(
                "device-paired",
                "设备已配对",
                detail=f"{grant.label or peer} 现在可以使用这台主机翻译",
                context="remote",
            )
        )

    def on_capture_failed(self, message: str) -> None:
        """Report a capture failure somewhere it cannot be silenced.

        Sticky, and offering the retry directly. This used to go out as a
        tray balloon after the overlay and the selection had already been
        destroyed, so a user whose notification settings suppress balloons
        lost both the result and any trace of the error.
        """
        self.notices.post(
            error_notice(
                "capture-failed",
                "截屏翻译失败",
                detail=message,
                context="capture",
                actions=(NoticeAction("retry-capture", "重新截图", primary=True),),
            )
        )

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
        self.captures.cancel()
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
