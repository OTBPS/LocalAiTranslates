from unittest.mock import Mock

import numpy as np

from screen_translator.core import CancellationToken, OcrLine
from screen_translator.engines import (
    KOREAN_REC,
    STANDARD_REC,
    OcrEngine,
    dominant_language,
    prefer_korean,
    representative_indices,
)


def polygon(x, y, width=100, height=20):
    return [(x, y), (x + width, y), (x + width, y + height), (x, y + height)]


def test_representative_samples_cover_image_height():
    polygons = [polygon(0, y, width=20 + y) for y in range(0, 900, 100)]
    chosen = representative_indices(polygons)
    ys = [polygons[index][0][1] for index in chosen]
    assert len(chosen) == 6
    assert min(ys) < 300 and max(ys) >= 600


def test_korean_router_requires_hangul_and_score():
    standard = {0: ("AAAA", 0.70), 1: ("Settings", 0.95)}
    korean = {0: ("설정을", 0.82), 1: ("Settings", 0.94)}
    assert prefer_korean(standard, korean)
    assert not prefer_korean(standard, {0: ("AAAA", 0.99), 1: ("Settings", 0.99)})


def test_dominant_language_scripts():
    def make(text):
        return OcrLine(polygon(0, 0), text, 0.95)

    assert dominant_language([make("Open settings")]) == "en"
    assert dominant_language([make("設定を開く")]) == "ja"
    assert dominant_language([make("설정을 열어 주세요")]) == "ko"
    assert dominant_language([make("打开设置")]) == "zh-Hans"


def test_explicit_korean_uses_only_korean_recognizer(tmp_path):
    class Detector:
        def predict(self, image, **kwargs):
            return [{"dt_polys": [polygon(0, 0)]}]

    engine = OcrEngine(tmp_path, allow_cpu=True)
    engine.device = "cpu"
    engine.mode = "CPU（速度较慢）"
    engine.detector = Detector()
    engine._predict = Mock(return_value={0: ("설정", 0.99)})
    result = engine.recognize(np.zeros((30, 120, 3), np.uint8), "ko", CancellationToken(), lambda _: None)
    assert result.detected_language == "ko"
    assert engine._predict.call_args.args[0] == KOREAN_REC
    assert all(call.args[0] != STANDARD_REC for call in engine._predict.call_args_list)


def test_auto_warmup_primes_detector_and_both_recognizers(tmp_path):
    engine = OcrEngine(tmp_path, allow_cpu=True)
    engine.device = "cpu"
    engine.mode = "CPU（速度较慢）"
    engine.detector = Mock()
    engine.detector.predict.return_value = []
    engine._predict = Mock(return_value={0: ("warmup", 0.99)})

    engine.warmup("auto", CancellationToken(), lambda _: None)

    assert [call.args[0] for call in engine._predict.call_args_list] == [STANDARD_REC, KOREAN_REC]


def test_failed_warmup_resets_engine_for_real_capture(tmp_path):
    engine = OcrEngine(tmp_path, allow_cpu=True)
    engine.device = "gpu:0"
    engine.mode = "CUDA"
    engine.detector = Mock()
    engine.detector.predict.side_effect = RuntimeError("transient")
    engine.recognizers[STANDARD_REC] = object()

    try:
        engine.warmup("en", CancellationToken(), lambda _: None)
    except RuntimeError:
        pass

    assert engine.detector is None
    assert engine.recognizers == {}
    assert engine.device is None and engine.mode == "未加载"
