"""Use-case controller for manually entered text translation.

The view owns no translation logic and the capture controller owns no text
input logic.  This object turns a string plus a language pair into background
work, guarantees that only the newest request may update the view, and logs
counts and timings without ever recording user content.
"""

from __future__ import annotations

import logging
import threading
import time

from PySide6.QtCore import QObject, Signal

from .core import CancellationToken, Cancelled
from .inference import MANUAL, InferenceBusy, InferenceCoordinator
from .tasks import TaskRunner
from .text_segmenter import InputTooLong, segment_text

LOGGER = logging.getLogger(__name__)

EMPTY_INPUT_MESSAGE = "请输入要翻译的文本"
SAME_LANGUAGE_MESSAGE = "输入和输出语言相同，已原样返回"
NOTHING_TO_TRANSLATE_MESSAGE = "没有可翻译的文字"


class ManualTranslationController(QObject):
    """Run one manual translation at a time and discard superseded results."""

    started = Signal(int)
    progress = Signal(int, str)
    finished = Signal(int, str)
    failed = Signal(int, str)
    cancelled = Signal(int)

    def __init__(self, coordinator: InferenceCoordinator, tasks: TaskRunner, parent: QObject | None = None):
        super().__init__(parent)
        self._coordinator = coordinator
        self._tasks = tasks
        self._lock = threading.Lock()
        self._request_id = 0
        self._token: CancellationToken | None = None

    @property
    def request_id(self) -> int:
        with self._lock:
            return self._request_id

    @property
    def active(self) -> bool:
        with self._lock:
            return self._token is not None

    def _is_current(self, request_id: int) -> bool:
        with self._lock:
            return request_id == self._request_id

    def _begin(self) -> int:
        with self._lock:
            previous = self._token
            self._request_id += 1
            self._token = None
            request_id = self._request_id
        if previous is not None:
            previous.cancel()
        return request_id

    def cancel(self) -> None:
        with self._lock:
            token = self._token
            self._token = None
        if token is not None:
            token.cancel()

    def translate(self, text: str, source_language: str, target_language: str) -> int:
        request_id = self._begin()
        self.started.emit(request_id)
        if not text.strip():
            self.failed.emit(request_id, EMPTY_INPUT_MESSAGE)
            return request_id
        try:
            document = segment_text(text)
        except InputTooLong as error:
            self.failed.emit(request_id, str(error))
            return request_id
        if source_language != "auto" and source_language == target_language:
            self.progress.emit(request_id, SAME_LANGUAGE_MESSAGE)
            self.finished.emit(request_id, text)
            return request_id
        if not document.translatable_count:
            self.progress.emit(request_id, NOTHING_TO_TRANSLATE_MESSAGE)
            self.finished.emit(request_id, text)
            return request_id

        token = CancellationToken()
        with self._lock:
            self._token = token
        self._coordinator.register_manual(token)
        blocks = document.blocks()
        characters = len(text)

        def run():
            started = time.monotonic()
            status = "ok"
            device = "未加载"
            model_id = adapter_id = None
            try:
                with self._coordinator.reserve(MANUAL) as port:
                    token.check()
                    if not self._is_current(request_id):
                        raise Cancelled()
                    translated = port.translate(
                        blocks,
                        token,
                        lambda message: self.progress.emit(request_id, message),
                        source_language,
                        target_language,
                        None,
                    )
                    device = getattr(port, "mode", device)
                    model = getattr(port, "model", None)
                    model_id = getattr(model, "model_id", None)
                    adapter_id = getattr(port, "adapter_id", None)
                values = {item.block.block_id: item.text for item in translated}
                token.check()
                if self._is_current(request_id):
                    self.finished.emit(request_id, document.assemble(values))
            except Cancelled:
                status = "cancelled"
                if self._is_current(request_id):
                    self.cancelled.emit(request_id)
            except InferenceBusy as error:
                status = "busy"
                if self._is_current(request_id):
                    self.failed.emit(request_id, str(error))
            except Exception as error:
                status = f"error:{type(error).__name__}"
                message = (
                    str(error)
                    if isinstance(error, RuntimeError)
                    else f"翻译失败（{type(error).__name__}），请稍后重试"
                )
                if self._is_current(request_id):
                    self.failed.emit(request_id, message)
            finally:
                self._coordinator.release_manual(token)
                with self._lock:
                    if self._token is token:
                        self._token = None
                LOGGER.info(
                    "Manual translation id=%d chars=%d segments=%d source=%s target=%s "
                    "model=%s adapter=%s device=%s elapsed_ms=%.1f status=%s",
                    request_id,
                    characters,
                    len(blocks),
                    source_language,
                    target_language,
                    model_id,
                    adapter_id,
                    device,
                    (time.monotonic() - started) * 1000,
                    status,
                )

        self._tasks.start(run, name=f"manual-translation-{request_id}")
        return request_id
