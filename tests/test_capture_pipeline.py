"""The capture pipeline, exercised as an object rather than through a fake self.

This behaviour used to be reachable only by building a `SimpleNamespace`
that impersonated the controller and calling an unbound method on it. Every
assertion below runs without a QApplication, without OpenCV and without a
controller, which is the point of extracting it.
"""

import numpy
import pytest

from screen_translator.capture import (
    CaptureOutcome,
    CapturePipeline,
    CaptureRequest,
    describe_failure,
)
from screen_translator.capture.pipeline import NO_TEXT_MESSAGE
from screen_translator.core import (
    CancellationToken,
    Cancelled,
    OcrLine,
    OcrResult,
    TranslatedBlock,
)
from screen_translator.inference import MANUAL, InferenceBusy, InferenceCoordinator

IMAGE = object()


def line(text="Hello"):
    return OcrLine([(0, 0), (80, 0), (80, 18), (0, 18)], text, 0.99)


class FakeOcr:
    mode = "CUDA"

    def __init__(self, lines=None, device="CUDA", timings=None):
        self._lines = [line()] if lines is None else lines
        self._device = device
        self._timings = timings or {"total": 12.0}
        self.calls = []

    def recognize(self, image, source_language, token, progress):
        self.calls.append((image, source_language))
        progress("正在识别文字…")
        return OcrResult(list(self._lines), "en", self._device, dict(self._timings))


class FakeEngine:
    mode = "CUDA"
    last_metrics = {"batches": 2, "quality_retries": 1, "format_repairs": 3}

    def __init__(self, behaviour=None):
        self.behaviour = behaviour

    def translate(self, blocks, token, progress, source, target, detected):
        if self.behaviour:
            self.behaviour(blocks, token, progress)
        progress("正在翻译 1/1")
        return [TranslatedBlock(block, f"译{block.text}") for block in blocks]


class FakeRenderer:
    def __init__(self):
        self.calls = []

    def render(self, original, translated, token, target_language):
        self.calls.append((original, tuple(translated), target_language))
        return "rendered-image"


def build(ocr=None, engine=None, renderer=None, **kwargs):
    arbiter = InferenceCoordinator(lambda: engine or FakeEngine())
    pipeline = CapturePipeline(
        ocr_provider=lambda: ocr or FakeOcr(),
        inference=arbiter,
        renderer_factory=lambda: renderer or FakeRenderer(),
        to_bgr=lambda _image: numpy.zeros((4, 4, 3), "uint8"),
        **kwargs,
    )
    return pipeline, arbiter


def request(source="en", target="zh-Hans"):
    return CaptureRequest(IMAGE, source, target)


def test_a_capture_produces_a_rendered_result_and_its_parts():
    renderer = FakeRenderer()
    pipeline, _arbiter = build(renderer=renderer)

    outcome = pipeline.run(request(), CancellationToken(), lambda _text: None)

    assert isinstance(outcome, CaptureOutcome)
    assert outcome.rendered == "rendered-image"
    assert [item.text for item in outcome.translated] == ["译Hello"]
    assert outcome.detected_language == "en"
    assert outcome.block_count == 1
    assert outcome.device == "CUDA"
    assert renderer.calls[0][2] == "zh-Hans"


def test_the_translated_blocks_are_kept_for_the_result_layer():
    # "Copy translation" must not need a second trip through the model.
    pipeline, _arbiter = build()

    outcome = pipeline.run(request(), CancellationToken(), lambda _text: None)

    assert outcome.translated and all(
        isinstance(item, TranslatedBlock) for item in outcome.translated
    )


def test_the_inference_slot_is_held_for_the_whole_translation():
    observed = {}

    def behaviour(_blocks, _token, _progress):
        observed["owner"] = arbiter.owner
        try:
            with arbiter.reserve(MANUAL):
                observed["manual"] = "granted"
        except InferenceBusy:
            observed["manual"] = "refused"

    pipeline, arbiter = build(engine=FakeEngine(behaviour))

    pipeline.run(request(), CancellationToken(), lambda _text: None)

    # The fallback path inside TranslationEngine stops the server mid-flight;
    # releasing the slot early would let another caller stream into it.
    assert observed == {"owner": "capture", "manual": "refused"}
    assert arbiter.owner is None


def test_the_slot_is_released_when_translation_fails():
    def behaviour(*_args):
        raise RuntimeError("14B 回退也失败")

    pipeline, arbiter = build(engine=FakeEngine(behaviour))

    with pytest.raises(RuntimeError, match="14B 回退也失败"):
        pipeline.run(request(), CancellationToken(), lambda _text: None)

    assert arbiter.owner is None


def test_a_page_with_no_text_is_a_readable_failure():
    pipeline, _arbiter = build(ocr=FakeOcr(lines=[]))

    with pytest.raises(RuntimeError, match=NO_TEXT_MESSAGE):
        pipeline.run(request(), CancellationToken(), lambda _text: None)


def test_progress_from_both_stages_reaches_the_caller():
    messages = []
    pipeline, _arbiter = build()

    pipeline.run(request(), CancellationToken(), messages.append)

    assert "正在识别文字…" in messages
    assert "正在翻译 1/1" in messages


def test_a_cancelled_token_stops_before_returning():
    token = CancellationToken()

    def behaviour(*_args):
        token.cancel()

    pipeline, _arbiter = build(engine=FakeEngine(behaviour))

    with pytest.raises(Cancelled):
        pipeline.run(request(), token, lambda _text: None)


def test_the_detected_language_is_reported_as_soon_as_it_is_known():
    seen = []
    pipeline, _arbiter = build(on_language_detected=seen.append)

    pipeline.run(request(), CancellationToken(), lambda _text: None)

    assert seen == ["en"]


def test_metrics_are_reported_as_values_rather_than_a_log_line():
    recorded = []
    pipeline, _arbiter = build(metrics=recorded.append, clock=iter([0.0, 1.0, 2.0, 4.0]).__next__)

    pipeline.run(request(), CancellationToken(), lambda _text: None)

    (values,) = recorded
    assert values["blocks"] == 1
    assert values["batches"] == 2
    assert values["retries"] == 1
    assert values["format_repairs"] == 3
    assert values["translation"] == pytest.approx(1000.0)
    assert values["render"] == pytest.approx(2000.0)


def test_the_language_pair_is_passed_through_unchanged():
    seen = {}

    def behaviour(_blocks, _token, _progress):
        seen["called"] = True

    engine = FakeEngine(behaviour)
    original = engine.translate
    captured = {}

    def recording(blocks, token, progress, source, target, detected):
        captured.update(source=source, target=target, detected=detected)
        return original(blocks, token, progress, source, target, detected)

    engine.translate = recording
    pipeline, _arbiter = build(engine=engine)

    pipeline.run(request("ja", "ko"), CancellationToken(), lambda _text: None)

    assert captured == {"source": "ja", "target": "ko", "detected": "en"}


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (RuntimeError("没有识别到清晰的横排文字"), "没有识别到清晰的横排文字"),
        (KeyError("internal"), "处理失败（KeyError）"),
        (OSError("C:/secret/path.gguf"), "处理失败（OSError）"),
    ],
)
def test_failures_are_described_without_leaking_internals(error, expected):
    described = describe_failure(error)

    assert expected in described
    if not isinstance(error, RuntimeError):
        # A file path or a raw message would be shown to the user verbatim.
        assert str(error) not in described
