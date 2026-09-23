"""Stable application-facing contracts for replaceable infrastructure."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Protocol

from .core import CancellationToken, OcrResult, TextBlock, TranslatedBlock

if TYPE_CHECKING:
    # Only ``RendererPort`` mentions Qt, and only in an annotation.  Keeping
    # the import behind ``TYPE_CHECKING`` lets the headless remote service and
    # a client build without the widget stack import these contracts.
    from PySide6.QtGui import QImage

ProgressCallback = Callable[[str], None]


class OcrPort(Protocol):
    mode: str

    def ready(self) -> bool:
        """Whether a recognition attempted right now could succeed.

        Must be cheap and non-blocking: it is polled from the UI thread every
        time the capture hotkey is pressed.
        """
        ...

    def warmup(
        self,
        source_language: str,
        token: CancellationToken,
        progress: ProgressCallback,
    ) -> None: ...

    def recognize(
        self,
        image: object,
        source_language: str,
        token: CancellationToken,
        progress: ProgressCallback,
    ) -> OcrResult: ...


class TranslationPort(Protocol):
    mode: str

    def ready(self) -> bool:
        """Whether a translation attempted right now could succeed."""
        ...

    def start(self, token: CancellationToken, progress: ProgressCallback) -> None: ...

    def stop(self) -> None: ...

    def translate(
        self,
        blocks: Sequence[TextBlock],
        token: CancellationToken,
        progress: ProgressCallback,
        source_language: str = "auto",
        target_language: str = "zh-Hans",
        detected_language: str | None = None,
    ) -> list[TranslatedBlock]: ...


class RendererPort(Protocol):
    def render(
        self,
        original: QImage,
        translated: Sequence[TranslatedBlock],
        token: CancellationToken,
        target_language: str = "zh-Hans",
    ) -> QImage: ...
