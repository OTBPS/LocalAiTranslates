"""Stable application-facing contracts for replaceable infrastructure."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Protocol

from PySide6.QtGui import QImage

from .core import CancellationToken, OcrResult, TextBlock, TranslatedBlock

ProgressCallback = Callable[[str], None]


class OcrPort(Protocol):
    mode: str

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
