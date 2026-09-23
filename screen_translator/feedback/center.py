"""Dispatching notices to whatever surfaces exist right now.

Callers post a notice; the centre decides where it lands and keeps a short
history. History matters because the tray is unreliable -- Windows can
suppress balloons entirely -- so anything important must remain findable
after the transient copy disappears.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from typing import Protocol

from PySide6.QtCore import QObject, Signal

from .notices import Lifetime, Notice, Surface, route, supersedes

LOGGER = logging.getLogger(__name__)

HISTORY_LIMIT = 50


class NoticeSink(Protocol):
    surface: Surface

    def present(self, notice: Notice) -> None: ...

    def revoke(self, notice_id: str) -> None: ...

    def available(self) -> bool:
        """Whether this surface can show something to the user right now."""
        ...


class NoticeCenter(QObject):
    """The one place a notice enters the user interface.

    Must be called from the UI thread. Background workers report through the
    existing signal-with-generation pattern and the flow layer turns the
    result into a notice; routing a notice straight from a worker would put
    widget mutation back on a background thread, which is exactly what the
    architecture forbids.
    """

    posted = Signal(object)
    revoked = Signal(str)
    action_invoked = Signal(str, str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._sinks: list[NoticeSink] = []
        self._active: dict[str, Notice] = {}
        self._history: list[Notice] = []

    def register_sink(self, sink: NoticeSink) -> None:
        self._sinks.append(sink)

    def surfaces(self) -> set[Surface]:
        return {sink.surface for sink in self._sinks if sink.available()}

    def post(self, notice: Notice) -> tuple[Surface, ...]:
        existing = self._active.get(notice.notice_id)
        if existing is not None and not supersedes(notice, existing):
            return ()
        targets = route(notice, self.surfaces())
        if not targets:
            # Nowhere to show it. Recording it is the difference between a
            # message the user can still find and one that never existed.
            LOGGER.info("Notice %s had no surface: %s", notice.notice_id, notice.title)
        for sink in self._sinks:
            if sink.surface in targets:
                sink.present(notice)
        if notice.persistent:
            self._active[notice.notice_id] = notice
        elif existing is not None:
            self._active.pop(notice.notice_id, None)
        self._remember(notice)
        self.posted.emit(notice)
        return targets

    def replay(self) -> tuple[Notice, ...]:
        """Re-present still-active notices to whatever is on screen now.

        A capture failure happens while the settings window is hidden, so at
        that moment the only available surface is the tray -- which Windows
        may suppress. Replaying when a real surface appears is what stops the
        message from being lost for good.
        """
        surfaces = self.surfaces()
        replayed = []
        for notice in self._active.values():
            targets = route(notice, surfaces)
            for sink in self._sinks:
                if sink.surface in targets:
                    sink.present(notice)
            if targets:
                replayed.append(notice)
        return tuple(replayed)

    def revoke(self, notice_id: str) -> None:
        if self._active.pop(notice_id, None) is None:
            return
        for sink in self._sinks:
            sink.revoke(notice_id)
        self.revoked.emit(notice_id)

    def invoke(self, notice_id: str, action_id: str) -> None:
        self.action_invoked.emit(notice_id, action_id)

    def active(self, context: str = "") -> tuple[Notice, ...]:
        items = self._active.values()
        if context:
            items = [item for item in items if item.context == context]
        return tuple(items)

    def history(self, limit: int = HISTORY_LIMIT) -> tuple[Notice, ...]:
        return tuple(self._history[-limit:])

    def _remember(self, notice: Notice) -> None:
        if notice.lifetime == Lifetime.PROGRESS:
            # Progress refreshes many times a second; keeping every frame
            # would bury everything else in the history.
            return
        self._history = [
            item for item in self._history if item.notice_id != notice.notice_id
        ][-HISTORY_LIMIT + 1 :]
        self._history.append(notice)


def connect_actions(
    center: NoticeCenter, handler: Callable[[str, str], None]
) -> None:
    center.action_invoked.connect(handler)


def notices_for(center: NoticeCenter, contexts: Iterable[str]) -> tuple[Notice, ...]:
    wanted = set(contexts)
    return tuple(item for item in center.active() if item.context in wanted)
