"""What a new installation should be told, and where to send it.

First run used to be: a tray balloon saying the models were missing, the
settings window opening on whichever tab it felt like, and a default model
of 10.5 GB chosen for the user without mentioning the size. Whether any of
that happened at all depended on a boolean passed through two layers.

The decision is a pure function of four observable facts, so the first-run
experience becomes something that can be regression-tested rather than
something only discoverable by reinstalling. Nothing here is written to
disk except `onboarding_completed`; the stage is always derived.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .core import REMOTE_MODE, Config
from .models import TRANSLATION_MODELS
from .navigation import Destination


class StartupIntent(StrEnum):
    """Why the process is running, which is not what it should show."""

    #: The user started the application. Show the window only if something
    #: needs doing.
    LAUNCH = "launch"
    #: The user explicitly asked for the window, or a second copy did.
    ACTIVATE = "activate"
    #: Windows started it at login. Stay in the tray, whatever else is true.
    AUTOSTART = "autostart"


class Stage(StrEnum):
    #: Nothing to do; the application works.
    READY = "ready"
    #: This build cannot run models locally and no host is configured.
    NEEDS_REMOTE = "needs-remote"
    #: Local inference is possible but the weights are not on disk.
    NEEDS_MODEL = "needs-model"
    #: A host is configured but not answering.
    HOST_UNREACHABLE = "host-unreachable"


@dataclass(frozen=True)
class OnboardingPlan:
    stage: Stage
    #: Whether to bring the settings window forward without being asked.
    open_settings: bool = False
    destination: Destination | None = None
    title: str = ""
    detail: str = ""
    action_label: str = ""

    @property
    def blocking(self) -> bool:
        """Whether a capture would fail right now."""
        return self.stage is not Stage.READY


def describe_download(model_id: str) -> str:
    """Name the size before the user commits to it, not after."""
    model = TRANSLATION_MODELS.get(model_id)
    if model is None:
        return "需要先下载翻译模型"
    return f"需要下载 {model.display_name}，约 {model.approximate_size_gb:g} GB"


def evaluate(
    config: Config,
    *,
    backend_ready: bool,
    local_runtime: bool,
    intent: StartupIntent = StartupIntent.LAUNCH,
) -> OnboardingPlan:
    """Decide what a user who has just arrived needs to be told.

    `intent` only decides whether the window is allowed to appear. It never
    changes the stage: a login launch that cannot translate is still an
    installation that cannot translate, and the tray still says so.
    """
    if backend_ready:
        return OnboardingPlan(Stage.READY)

    interactive = intent is not StartupIntent.AUTOSTART
    if config.mode == REMOTE_MODE:
        return OnboardingPlan(
            Stage.HOST_UNREACHABLE,
            open_settings=interactive,
            destination=Destination.REMOTE_PAIRING,
            title="连接不到主机",
            detail="主机未响应，请确认它已开机并启用了跨设备服务",
            action_label="检查主机连接",
        )
    if not local_runtime:
        # The thin client can never download its way out of this.
        return OnboardingPlan(
            Stage.NEEDS_REMOTE,
            open_settings=interactive,
            destination=Destination.REMOTE_MODE,
            title="此版本需要连接主机",
            detail="精简版不包含本地推理运行时，请填写主机地址后使用",
            action_label="设置主机",
        )
    return OnboardingPlan(
        Stage.NEEDS_MODEL,
        open_settings=interactive,
        destination=Destination.MODEL_DOWNLOAD,
        title="还差一步就能用",
        detail=describe_download(config.translation_model),
        action_label="下载模型",
    )


def intent_from_arguments(arguments) -> StartupIntent:
    """Read the launch reason from the command line.

    The registry Run entry passes ``--autostart``, so a login launch says
    so rather than being inferred. Guessing it from "are the models ready"
    is what let a login on an unconfigured machine open a window nobody
    asked for.
    """
    if "--autostart" in arguments:
        return StartupIntent.AUTOSTART
    if "--show-settings" in arguments:
        return StartupIntent.ACTIVATE
    return StartupIntent.LAUNCH
