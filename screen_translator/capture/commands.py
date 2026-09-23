"""What the user can do during a capture, and why not when they cannot.

The overlay used to answer this with scattered ``if c.state == ...`` checks,
and anything that fell through them did nothing at all -- clicking during
processing produced no response, leaving no way to tell a missed click from
an ignored one.

Expressing it as a pure function over the state makes the silent case
impossible: a command is either in the allowed set, or ``describe_block``
has a sentence explaining its absence.
"""

from __future__ import annotations

from enum import StrEnum

from ..session import SessionState
from .selection import MIN_SELECTION, SelectionModel


class CaptureCommand(StrEnum):
    BEGIN_DRAG = "begin-drag"
    UPDATE_DRAG = "update-drag"
    END_DRAG = "end-drag"
    GRAB_HANDLE = "grab-handle"
    DRAG_HANDLE = "drag-handle"
    RELEASE_HANDLE = "release-handle"
    NUDGE = "nudge"
    CONFIRM = "confirm"
    RESELECT = "reselect"
    CANCEL = "cancel"
    RETRY = "retry"
    TOGGLE_VIEW = "toggle-view"
    RETRANSLATE = "retranslate"
    COPY_TEXT = "copy-text"
    COPY_IMAGE = "copy-image"
    SAVE_IMAGE = "save-image"
    SWAP_LANGUAGES = "swap-languages"

    @property
    def label(self) -> str:
        return _LABELS[self]


_LABELS = {
    CaptureCommand.CONFIRM: "翻译选区",
    CaptureCommand.RESELECT: "重新框选",
    CaptureCommand.CANCEL: "取消",
    CaptureCommand.RETRY: "重试",
    CaptureCommand.TOGGLE_VIEW: "切换原图/译文",
    CaptureCommand.RETRANSLATE: "重新翻译",
    CaptureCommand.COPY_TEXT: "复制译文",
    CaptureCommand.COPY_IMAGE: "复制译图",
    CaptureCommand.SAVE_IMAGE: "保存译图…",
    CaptureCommand.SWAP_LANGUAGES: "对调语言并重译",
    CaptureCommand.BEGIN_DRAG: "开始框选",
    CaptureCommand.UPDATE_DRAG: "调整框选",
    CaptureCommand.END_DRAG: "结束框选",
    CaptureCommand.GRAB_HANDLE: "拖动控制点",
    CaptureCommand.DRAG_HANDLE: "移动控制点",
    CaptureCommand.RELEASE_HANDLE: "放开控制点",
    CaptureCommand.NUDGE: "微调选区",
}

_DRAWING = frozenset(
    {
        CaptureCommand.BEGIN_DRAG,
        CaptureCommand.UPDATE_DRAG,
        CaptureCommand.END_DRAG,
        CaptureCommand.CANCEL,
    }
)
_ADJUSTING = frozenset(
    {
        CaptureCommand.GRAB_HANDLE,
        CaptureCommand.DRAG_HANDLE,
        CaptureCommand.RELEASE_HANDLE,
        CaptureCommand.NUDGE,
        CaptureCommand.RESELECT,
        CaptureCommand.CANCEL,
    }
)
_RESULT = frozenset(
    {
        CaptureCommand.TOGGLE_VIEW,
        CaptureCommand.RETRANSLATE,
        CaptureCommand.COPY_TEXT,
        CaptureCommand.COPY_IMAGE,
        CaptureCommand.SAVE_IMAGE,
        CaptureCommand.SWAP_LANGUAGES,
        CaptureCommand.CANCEL,
    }
)
_FAILED = frozenset(
    {CaptureCommand.RETRY, CaptureCommand.RESELECT, CaptureCommand.CANCEL}
)


def allowed_commands(
    state: SessionState, selection: SelectionModel, *, has_result: bool = False
) -> frozenset[CaptureCommand]:
    if state == SessionState.SELECTING:
        allowed = set(_DRAWING)
        if selection.rect is not None:
            allowed |= _ADJUSTING
            if selection.valid:
                allowed.add(CaptureCommand.CONFIRM)
        return frozenset(allowed)
    if state == SessionState.ADJUSTING:
        allowed = set(_ADJUSTING)
        if selection.valid:
            allowed.add(CaptureCommand.CONFIRM)
        return frozenset(allowed)
    if state == SessionState.PROCESSING:
        # Everything else is refused while the model runs, but cancelling
        # must always be possible -- a cold start can take most of a minute.
        return frozenset({CaptureCommand.CANCEL})
    if state == SessionState.RESULT:
        allowed = set(_RESULT)
        if not has_result:
            allowed -= {
                CaptureCommand.COPY_TEXT,
                CaptureCommand.COPY_IMAGE,
                CaptureCommand.SAVE_IMAGE,
            }
        return frozenset(allowed)
    if state == SessionState.FAILED:
        return _FAILED
    return frozenset({CaptureCommand.CANCEL})


def describe_block(
    command: CaptureCommand, state: SessionState, selection: SelectionModel
) -> str:
    """Why ``command`` is unavailable right now, in words worth showing."""
    if command is CaptureCommand.CONFIRM and not selection.valid:
        if selection.rect is None:
            return "请先拖动框选文字区域"
        return f"选区太小，至少需要 {MIN_SELECTION} × {MIN_SELECTION}"
    if state == SessionState.PROCESSING:
        return "正在处理，按 Esc 取消"
    if state == SessionState.CANCELLING:
        return "正在取消…"
    return f"当前无法{command.label}"
