"""Small managed runner for the application's background work."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

LOGGER = logging.getLogger(__name__)


class TaskRunner:
    """Start named daemon workers, track them, and join briefly on shutdown."""

    def __init__(self):
        self._lock = threading.Lock()
        self._threads: set[threading.Thread] = set()
        self._closed = False

    def start(self, target: Callable[[], None], *, name: str) -> threading.Thread:
        with self._lock:
            if self._closed:
                raise RuntimeError("后台任务管理器已关闭")

        def run():
            try:
                target()
            except Exception:
                LOGGER.exception("Unhandled background task failure: %s", name)
            finally:
                with self._lock:
                    self._threads.discard(threading.current_thread())

        thread = threading.Thread(target=run, daemon=True, name=name)
        with self._lock:
            self._threads.add(thread)
        thread.start()
        return thread

    def shutdown(self, timeout: float = 2.0) -> None:
        with self._lock:
            self._closed = True
            threads = list(self._threads)
        deadline = time.monotonic() + max(0.0, timeout)
        for thread in threads:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            thread.join(remaining)

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self._threads)
