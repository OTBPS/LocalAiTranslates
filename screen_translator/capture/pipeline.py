"""One screenshot, from pixels to a rendered translation.

This was a closure inside ``Controller.selected``, which meant it could only
be exercised by faking ``self`` with a namespace and calling an unbound
method -- four test files still do that. As an object with its dependencies
injected it runs without a ``QApplication``, without OpenCV, and without a
controller.

It deliberately knows nothing about sessions, generations or signals. It
takes a request, reports progress through a callback, and either returns an
outcome or raises. Deciding whether a result is still wanted belongs to the
caller that owns the session.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from ..contracts import OcrPort, ProgressCallback, RendererPort
from ..core import CancellationToken, TextBlock, TranslatedBlock, merge_lines
from ..inference import CAPTURE, InferenceCoordinator

LOGGER = logging.getLogger(__name__)
PERFORMANCE_LOGGER = logging.getLogger("screen_translator.performance")

NO_TEXT_MESSAGE = "没有识别到清晰的横排文字"


@dataclass(frozen=True)
class CaptureRequest:
    """Everything one capture needs. The image stays opaque to this layer."""

    image: object
    source_language: str
    target_language: str


@dataclass(frozen=True)
class CaptureOutcome:
    rendered: object
    # Kept so the result layer can offer "copy translation" without going
    # back to the model.
    translated: tuple[TranslatedBlock, ...] = ()
    detected_language: str = "auto"
    block_count: int = 0
    device: str = ""
    timings_ms: dict[str, float] = field(default_factory=dict)


class CapturePipeline:
    def __init__(
        self,
        *,
        ocr_provider: Callable[[], OcrPort],
        inference: InferenceCoordinator,
        renderer_factory: Callable[[], RendererPort],
        to_bgr: Callable[[object], object],
        merge: Callable[[Sequence[object]], list[TextBlock]] = merge_lines,
        clock: Callable[[], float] = time.monotonic,
        on_language_detected: Callable[[str], None] | None = None,
        metrics: Callable[[dict[str, object]], None] | None = None,
    ):
        self._ocr_provider = ocr_provider
        self._inference = inference
        self._renderer_factory = renderer_factory
        self._to_bgr = to_bgr
        self._merge = merge
        self._clock = clock
        self._on_language_detected = on_language_detected
        self._metrics = metrics if metrics is not None else _log_metrics

    def run(
        self,
        request: CaptureRequest,
        token: CancellationToken,
        progress: ProgressCallback,
    ) -> CaptureOutcome:
        """Recognise, translate and render. Raises ``Cancelled`` or ``RuntimeError``."""
        ocr_result = self._ocr_provider().recognize(
            self._to_bgr(request.image), request.source_language, token, progress
        )
        if self._on_language_detected is not None:
            self._on_language_detected(ocr_result.detected_language)
        blocks = self._merge(ocr_result.lines)
        if not blocks:
            raise RuntimeError(NO_TEXT_MESSAGE)

        translation_started = self._clock()
        # The slot is held for the whole translation on purpose: the
        # fallback path inside TranslationEngine stops the server mid-flight
        # and must never do so while another caller is streaming.
        with self._inference.reserve(CAPTURE) as engine:
            translated = engine.translate(
                blocks,
                token,
                progress,
                request.source_language,
                request.target_language,
                ocr_result.detected_language,
            )
            engine_metrics = dict(getattr(engine, "last_metrics", {}) or {})
        translation_ms = (self._clock() - translation_started) * 1000

        render_started = self._clock()
        rendered = self._renderer_factory().render(
            request.image, translated, token, request.target_language
        )
        render_ms = (self._clock() - render_started) * 1000

        timings = {
            "ocr": ocr_result.timings_ms.get("total", 0.0),
            "translation": translation_ms,
            "render": render_ms,
        }
        self._metrics(
            {
                "device": ocr_result.device,
                "blocks": len(blocks),
                "batches": engine_metrics.get("batches", 0),
                "retries": engine_metrics.get("quality_retries", 0),
                "format_repairs": engine_metrics.get("format_repairs", 0),
                **timings,
            }
        )
        token.check()
        return CaptureOutcome(
            rendered=rendered,
            translated=tuple(translated),
            detected_language=ocr_result.detected_language,
            block_count=len(blocks),
            device=ocr_result.device,
            timings_ms=timings,
        )


def describe_failure(error: Exception) -> str:
    """Turn an exception into something worth showing.

    ``RuntimeError`` is what this codebase uses for messages already written
    for a reader; anything else would leak a type name or a file path.
    """
    if isinstance(error, RuntimeError):
        return str(error)
    return f"处理失败（{type(error).__name__}），请检查模型或重新启动"


def _log_metrics(values: dict[str, object]) -> None:
    PERFORMANCE_LOGGER.info(
        "Pipeline timing ms device=%s blocks=%d batches=%d retries=%d format_repairs=%d "
        "ocr=%.1f translation=%.1f render=%.1f",
        values.get("device"),
        values.get("blocks", 0),
        values.get("batches", 0),
        values.get("retries", 0),
        values.get("format_repairs", 0),
        values.get("ocr", 0.0),
        values.get("translation", 0.0),
        values.get("render", 0.0),
    )
