"""What the application has to say, independent of where it is shown.

Eight separate channels grew up here: tray balloons, modal dialogs, the
overlay capsule, a status label buried in one card, status chips, the text
page's status line, the cross-device card's two lines, and the download
progress bar. The same meaning took a different shape depending on which code
path produced it -- "busy right now" was a balloon from the hotkey, a modal
from the save button, and a greyed-out button with no explanation on the text
page.

A notice describes the message. Where it lands is a routing decision made
against the surfaces that happen to exist at that moment, not something each
caller picks. Standard library only: this is domain, and the flow layer must
be able to raise a notice without importing a widget toolkit.
"""

from __future__ import annotations

from collections.abc import Set
from dataclasses import dataclass, field
from enum import StrEnum

from ..navigation import Destination

DEFAULT_TIMEOUT_MS = 6000


class Severity(StrEnum):
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    PROGRESS = "progress"


class Surface(StrEnum):
    """Somewhere a notice can appear. Modals are deliberately absent.

    A modal interrupts to ask a question; those go through
    :class:`~screen_translator.feedback.confirm.ConfirmationPort`. Everything
    routed here is reporting, and reporting must not block.
    """

    INLINE = "inline"
    OVERLAY = "overlay"
    TRAY = "tray"


class Lifetime(StrEnum):
    TRANSIENT = "transient"
    STICKY = "sticky"
    PROGRESS = "progress"


@dataclass(frozen=True)
class NoticeAction:
    """Something the user can do about the message.

    An error that only states what went wrong leaves the reader to find the
    control themselves; `destination` is what lets the message carry them
    there.
    """

    action_id: str
    label: str
    destination: Destination | None = None
    primary: bool = False


@dataclass(frozen=True)
class Notice:
    notice_id: str
    severity: Severity
    title: str
    detail: str = ""
    context: str = ""
    actions: tuple[NoticeAction, ...] = ()
    lifetime: Lifetime = Lifetime.TRANSIENT
    timeout_ms: int = DEFAULT_TIMEOUT_MS
    progress: float | None = None
    preferred: tuple[Surface, ...] = (Surface.INLINE,)

    @property
    def actionable(self) -> bool:
        return bool(self.actions)

    @property
    def persistent(self) -> bool:
        return self.lifetime in (Lifetime.STICKY, Lifetime.PROGRESS)


def route(notice: Notice, available: Set[Surface]) -> tuple[Surface, ...]:
    """Choose where to show ``notice`` among the surfaces that exist now.

    Preference order is the notice's own, filtered by availability. The tray
    is the fallback rather than a preference: Windows can suppress balloons
    entirely, so it is the least reliable place to put anything that matters.
    """
    chosen = tuple(surface for surface in notice.preferred if surface in available)
    if chosen:
        return chosen
    if Surface.TRAY in available:
        return (Surface.TRAY,)
    return ()


def supersedes(incoming: Notice, existing: Notice) -> bool:
    """Whether ``incoming`` should replace ``existing`` rather than stack.

    Identity is the notice id, so a progress update or a retry of the same
    operation refreshes one entry instead of piling up copies of itself.
    """
    return incoming.notice_id == existing.notice_id


def progress_notice(
    notice_id: str,
    title: str,
    fraction: float | None,
    *,
    detail: str = "",
    context: str = "",
    actions: tuple[NoticeAction, ...] = (),
) -> Notice:
    return Notice(
        notice_id=notice_id,
        severity=Severity.PROGRESS,
        title=title,
        detail=detail,
        context=context,
        actions=actions,
        lifetime=Lifetime.PROGRESS,
        progress=None if fraction is None else max(0.0, min(1.0, fraction)),
        preferred=(Surface.INLINE,),
    )


def error_notice(
    notice_id: str,
    title: str,
    *,
    detail: str = "",
    context: str = "",
    actions: tuple[NoticeAction, ...] = (),
    preferred: tuple[Surface, ...] = (Surface.INLINE,),
) -> Notice:
    """Errors stay put. A failure the user missed is a failure they cannot act on."""
    return Notice(
        notice_id=notice_id,
        severity=Severity.ERROR,
        title=title,
        detail=detail,
        context=context,
        actions=actions,
        lifetime=Lifetime.STICKY,
        preferred=preferred,
    )


def success_notice(
    notice_id: str, title: str, *, detail: str = "", context: str = ""
) -> Notice:
    return Notice(
        notice_id=notice_id,
        severity=Severity.SUCCESS,
        title=title,
        detail=detail,
        context=context,
    )


@dataclass(frozen=True)
class Occupancy:
    """Why an action is unavailable, in words a control can show.

    Disabling a control without saying why is the single most common
    complaint about this application's settings window; pairing every
    ``setEnabled(False)`` with this makes the reason unavoidable.
    """

    busy: bool = False
    reason: str = ""
    actions: tuple[NoticeAction, ...] = field(default_factory=tuple)

    def __bool__(self) -> bool:
        return self.busy
