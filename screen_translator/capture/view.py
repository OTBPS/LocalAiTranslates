"""What the capture overlay draws, as data.

The overlay used to reach back into the controller for a dozen attributes
while painting, which made both sides hard to change and impossible to test
apart. A view model is the seam: the flow layer decides what is true, the
overlay decides how it looks.

The split between ``message`` and ``hint`` is the point of the exercise.
There was one string, so the progress text overwrote "Esc 取消" exactly when
the wait was longest and the way out mattered most.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ..session import SessionState
from .commands import CaptureCommand
from .selection import Handle, Rect


@dataclass(frozen=True)
class OverlayViewModel:
    state: SessionState = SessionState.IDLE
    #: What is happening.
    message: str = ""
    #: What the user can do about it. Always rendered.
    hint: str = ""
    selection: Rect | None = None
    handles: tuple[tuple[Handle, Rect], ...] = ()
    show_translation: bool = True
    result: object | None = None
    result_rect: Rect | None = None
    commands: frozenset[CaptureCommand] = field(default_factory=frozenset)
    language_pair: str = ""
    elapsed_seconds: int = 0
    #: Index of the screen that shows the status capsule. Drawing it on every
    #: screen produced one copy per monitor instead of one per capture.
    capsule_screen: int = 0
    cursor: tuple[int, int] | None = None

    @property
    def animated(self) -> bool:
        """Whether anything on screen needs a repaint timer."""
        return self.state == SessionState.PROCESSING

    @property
    def badge(self) -> str:
        from .selection import describe_size

        return describe_size(self.selection)

    def allows(self, command: CaptureCommand) -> bool:
        return command in self.commands


class CaptureView(Protocol):
    def present(self, screens: object, model: OverlayViewModel) -> None: ...

    def update_model(self, model: OverlayViewModel) -> None: ...

    def dismiss(self) -> None: ...


STATE_LABELS = {
    SessionState.SELECTING: "选择区域",
    SessionState.ADJUSTING: "调整选区",
    SessionState.PROCESSING: "正在处理",
    SessionState.RESULT: "译文",
    SessionState.FAILED: "失败",
    SessionState.CANCELLING: "正在取消",
    SessionState.IDLE: "原图",
}


def state_label(model: OverlayViewModel) -> str:
    if model.state == SessionState.RESULT and not model.show_translation:
        return "原图"
    return STATE_LABELS.get(model.state, "原图")


def default_hint(model: OverlayViewModel) -> str:
    """The way out, phrased for the state the user is actually in."""
    if model.state == SessionState.SELECTING:
        return "拖动框选文字 · Esc 取消"
    if model.state == SessionState.ADJUSTING:
        if CaptureCommand.CONFIRM in model.commands:
            return "拖动控制点调整 · 回车翻译 · Esc 取消"
        return "选区太小，继续拖动调整 · Esc 取消"
    if model.state == SessionState.PROCESSING:
        # The elapsed count is what distinguishes "working" from "hung"
        # during a cold start, which can take most of a minute.
        return f"Esc 取消 · 已用 {model.elapsed_seconds} 秒"
    if model.state == SessionState.RESULT:
        return "左键切换原图/译文 · 右键更多操作 · Esc 退出"
    if model.state == SessionState.FAILED:
        return "回车重试 · R 重新框选 · Esc 放弃"
    return "Esc 退出"
