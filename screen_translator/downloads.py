"""Orchestration of model downloads.

This used to live in the settings window: the view created a cancellation
token, assigned it to the controller, started a background task and emitted
controller signals. A view that schedules work and mutates another object's
state is the reason "is anything busy?" had to be answered by inspecting a
token from six different places.

``install_models`` itself is untouched. Only who calls it, and what is known
about the call while it runs, changes here.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

from .core import Cancelled
from .download_session import DownloadSession, DownloadState
from .feedback import (
    NoticeAction,
    NoticeCenter,
    error_notice,
    progress_notice,
    success_notice,
)
from .models import install_models, isolate_model_for_redownload
from .tasks import TaskRunner

LOGGER = logging.getLogger(__name__)

NOTICE_ID = "model-download"


@dataclass(frozen=True)
class DownloadSnapshot:
    """What the interface needs to know, without reaching into the session."""

    state: DownloadState
    model_id: str = ""
    file_name: str = ""
    fraction: float | None = None
    detail: str = ""
    cancellable: bool = False

    @property
    def active(self) -> bool:
        return self.state in (
            DownloadState.PREPARING,
            DownloadState.DOWNLOADING,
            DownloadState.VERIFYING,
            DownloadState.CANCELLING,
        )


class DownloadCoordinator(QObject):
    """Run one model download at a time and report it as a notice."""

    changed = Signal(object)  # DownloadSnapshot
    completed = Signal(bool)  # success

    # Progress arrives on a worker thread; this signal is the hop back to the
    # UI thread, where the session and the notice centre may be touched.
    _observed = Signal(int, str, object, object)
    _finished = Signal(int, str, str)

    def __init__(
        self,
        *,
        tasks: TaskRunner,
        notices: NoticeCenter,
        installer: Callable[..., None] = install_models,
        isolator: Callable[..., object] = isolate_model_for_redownload,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._tasks = tasks
        self._notices = notices
        self._installer = installer
        self._isolator = isolator
        self._session = DownloadSession()
        self._observed.connect(self._on_observed)
        self._finished.connect(self._on_finished)

    @property
    def active(self) -> bool:
        return self._session.active

    @property
    def snapshot(self) -> DownloadSnapshot:
        session = self._session
        return DownloadSnapshot(
            state=session.state,
            model_id=session.model_id,
            file_name=session.file_name,
            fraction=session.fraction,
            detail=session.detail,
            cancellable=session.cancellable,
        )

    def start(self, model_dir: str, model_id: str) -> bool:
        if self._session.active:
            return False
        attempt = self._session.begin(model_id)
        token = self._session.token
        self._announce()
        self._notices.post(
            progress_notice(
                NOTICE_ID,
                f"正在下载 {model_id}",
                None,
                detail="正在连接…",
                context="download",
                actions=(NoticeAction("cancel-download", "取消下载"),),
            )
        )

        def run() -> None:
            outcome, detail = "completed", "模型下载和校验完成，可离线使用"
            try:
                self._installer(
                    model_dir,
                    token,
                    lambda name, current, total: self._observed.emit(
                        attempt, name, current, total
                    ),
                    model_id,
                )
            except Cancelled:
                outcome, detail = "cancelled", "下载已取消，下次可继续"
            except Exception as error:
                LOGGER.warning("Model download failed: %s", type(error).__name__)
                outcome = "failed"
                detail = f"下载失败：{type(error).__name__}，请检查网络后重试"
            self._finished.emit(attempt, outcome, detail)

        self._tasks.start(run, name=f"model-download-{attempt}")
        return True

    def redownload(
        self, model_dir: str, model_id: str, *, stop_translator: Callable[[], None]
    ) -> object:
        """Quarantine the current artifact, then download it again."""
        if self._session.active:
            return None
        stop_translator()
        backup = self._isolator(model_dir, model_id)
        self.start(model_dir, model_id)
        return backup

    def cancel(self) -> None:
        if not self._session.cancellable:
            return
        self._session.invalidate()
        self._announce()

    def shutdown(self) -> None:
        if self._session.token:
            self._session.token.cancel()

    def _on_observed(self, attempt: int, name: str, current: object, total: object) -> None:
        if not self._session.is_current(attempt):
            return
        self._session.observe(name, int(current or 0), int(total or 0))
        snapshot = self.snapshot
        self._notices.post(
            progress_notice(
                NOTICE_ID,
                f"正在下载 {snapshot.model_id}",
                snapshot.fraction,
                detail=_size_detail(self._session.received, self._session.total, name),
                context="download",
                actions=(NoticeAction("cancel-download", "取消下载"),),
            )
        )
        self._announce()

    def _on_finished(self, attempt: int, outcome: str, detail: str) -> None:
        # A late result from a superseded attempt must not overwrite the
        # state of the one that replaced it.
        if not self._session.is_current(attempt) and outcome != "cancelled":
            return
        self._notices.revoke(NOTICE_ID)
        if outcome == "completed":
            self._session.finish(DownloadState.COMPLETED, detail)
            self._notices.post(
                success_notice("model-download-done", "模型已就绪", detail=detail, context="download")
            )
        elif outcome == "cancelled":
            self._session.finish(DownloadState.IDLE, detail)
        else:
            self._session.finish(DownloadState.FAILED, detail)
            self._notices.post(
                error_notice(
                    "model-download-failed",
                    "模型下载失败",
                    detail=detail,
                    context="download",
                    actions=(NoticeAction("retry-download", "重试", primary=True),),
                )
            )
        self._announce()
        self.completed.emit(outcome == "completed")

    def _announce(self) -> None:
        self.changed.emit(self.snapshot)


def _size_detail(received: int, total: int, name: str) -> str:
    if total <= 0:
        return name
    return f"{name} · {received / 1e9:.2f} / {total / 1e9:.2f} GB"
